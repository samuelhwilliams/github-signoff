from flask import (
    Blueprint,
    Flask,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import LoginManager, current_user, login_required
from flask_login import login_user as _login_user
from flask_login import logout_user as _logout_user

from notifications_python_client.notifications import NotificationsAPIClient

from app import db
from app.auth import login_user, new_login_token_and_payload
from app.errors import GithubUnauthorized, HookAlreadyExists, TrelloUnauthorized
from app.forms import AuthorizeTrelloForm, ChooseGithubRepoForm, ChooseTrelloBoardForm, ChooseTrelloListForm, LoginForm
from app.github import GithubClient
from app.models import GithubRepo, LoginToken, PullRequestStatus, TrelloCard, TrelloList, User
from app.trello import TrelloClient
from app.updater import Updater
from app.utils import get_github_client, get_trello_client

main_blueprint = Blueprint("main", "main")


@main_blueprint.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET" and current_user.is_authenticated:
        return redirect(url_for(".dashboard"))

    form = LoginForm()

    if form.validate_on_submit():
        user = User.find_or_create(form.email.data)
        if user.active:
            user.active = False
        db.session.add(user)

        token, payload = new_login_token_and_payload(current_app, db, user)

        # notifications_client = NotificationsAPIClient(current_app.config["NOTIFY_API_KEY"])
        # notifications_client.send_email_notification(
        #     email_address=form.email.data,
        #     template_id=current_app.config["NOTIFY_TEMPLATE_LOGIN_LINK"],
        #     personalisation={"login_link": url_for(".login", payload=payload, _external=True)},
        # )

        print(
            form.email.data,
            current_app.config["NOTIFY_TEMPLATE_LOGIN_LINK"],
            {"login_link": url_for(".login", payload=payload, _external=True)},
        )

        db.session.commit()

        flash("A login link has been emailed to you. Please click it within 5 minutes.")

    return render_template("index.html", form=form)


@main_blueprint.route("/login/<payload>")
def login(payload):
    user = login_user(current_app, db, payload)
    if user:
        return redirect(url_for(".dashboard"))

    return redirect(url_for(".index"))


@main_blueprint.route("/dashboard")
@login_required
def dashboard():
    github_integrated, trello_integrated = current_user.github_token is not None, current_user.trello_token is not None

    if github_integrated:
        github_client = get_github_client(current_user)
        if github_client.is_token_valid() is False:
            flash("Your GitHub token may no longer be valid. Please revoke and re-authorize.", "warning")

    if trello_integrated:
        trello_client = get_trello_client(current_user)
        if trello_client.is_token_valid() is False:
            flash("Your Trello token may no longer be valid. Please revoke and re-authorize.", "warning")

    github_repos, trello_lists = [], []
    if github_integrated and trello_integrated:
        github_repos = GithubRepo.query.filter(GithubRepo.user_id == current_user.id).all()
        trello_lists = TrelloList.query.filter(TrelloList.user_id == current_user.id).all()

    return render_template(
        "dashboard.html",
        github_integrated=github_integrated,
        trello_integrated=trello_integrated,
        github_repos=github_repos,
        trello_lists=trello_lists,
    )


@main_blueprint.route("/github/integration", methods=["GET", "POST"])
@login_required
def integrate_github():
    if request.method == "POST":
        current_user.github_state = str(uuid.uuid4())
        db.session.add(current_user)
        db.session.commit()

        return redirect(
            GITHUB_OAUTH_URL.format(
                redirect_uri=url_for(".github_authorization_complete"),
                state=current_user.github_state,
                **GITHUB_OAUTH_SETTINGS,
            )
        )

    return render_template("integrate_github.html")


@main_blueprint.route("/github/integration/callback", methods=["POST"])
def github_callback():
    if request.headers["X-GitHub-Event"] == "ping":
        return jsonify(status="OK"), 200

    payload = request.json["pull_request"]
    repo_fullname = payload["head"]["repo"]["full_name"]

    try:
        github_repo = GithubRepo.query.filter(GithubRepo.fullname == repo_fullname).one()

    except NoResultFound:
        logger.warning(f"Callback received but no repository registered in database: {repo_fullname}")
        return jsonify(status="OK"), 200

    updater = Updater(db, github_repo.user)
    updater.sync_pull_request(
        id_=payload["id"], sha=payload["head"]["sha"], body=payload["body"], github_repo=github_repo
    )

    return jsonify(status="OK"), 200


@main_blueprint.route("/github/integration/complete")
@login_required
def github_authorization_complete():
    if request.args["state"] != current_user.github_state:
        flash("Invalid state from GitHub authentication. Possible man-in-the-middle attempt. Process aborted.")
        return redirect(url_for(".dashboard"))

    response = requests.get(
        GITHUB_TOKEN_URL,
        params={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": request.args["code"],
            "state": current_user.github_state,
        },
        headers={"Accept": "application/json"},
    )

    if response.status_code == 200:
        current_user.github_token = response.json()["access_token"]
        db.session.add(current_user)
        db.session.commit()
        flash("GitHub integration successful.")
        return redirect(url_for(".dashboard"))

    flash("Something went wrong with integration?" + str(response))
    return redirect(url_for(".dashboard"))


@main_blueprint.route("/github/choose-repos", methods=["GET", "POST"])
@login_required
def github_choose_repos():
    github_client = get_github_client(current_user)
    repo_form = ChooseGithubRepoForm(github_client.get_repos())

    if repo_form.validate_on_submit():
        github_client = get_github_client(current_user)
        repo_choices = dict(repo_form.repo_choice.choices)  # refactor
        chosen_repo_fullnames = {repo_choices.get(repo_choice) for repo_choice in repo_form.repo_choice.data}

        updater = Updater(db, current_user)
        updater.sync_repositories(chosen_repo_fullnames)

        return redirect(url_for(".dashboard"))

    existing_repos = GithubRepo.query.filter(GithubRepo.user_id == current_user.id).all()
    repo_form.repo_choice.data = [repo.fullname for repo in existing_repos]

    return render_template("select-repo.html", repo_form=repo_form)


@main_blueprint.route("/github/revoke", methods=["POST"])
@login_required
def revoke_github():
    github_client = get_github_client(current_user)
    if github_client.revoke_integration() is False:
        flash(
            (
                "Something went wrong revoking your GitHub integration. Please revoke it directly from "
                "https://github.com/settings/applications"
            ),
            "error",
        )

    current_user.github_token = None
    current_user.github_state = None
    db.session.add(current_user)
    db.session.commit()

    return redirect(url_for(".dashboard"))


@main_blueprint.route("/trello/integration", methods=["HEAD"])
def integrate_trello_head():
    return jsonify(status="OK"), 200


@main_blueprint.route("/trello/integration", methods=["POST"])
def trello_callback():
    data = json.loads(request.get_data(as_text=True))
    logging.debug("Trello callback data: " + request.get_data(as_text=True))
    if data.get("action", {}).get("type") == "updateCard":
        trello_cards = TrelloCard.query.filter(TrelloCard.card_id == data["action"]["data"]["card"]["shortLink"]).all()
        if trello_cards:
            updater = Updater(db, trello_cards[0].pull_request.user)
            updater.sync_trello_card(trello_cards)

    return jsonify(status="OK"), 200


@main_blueprint.route("/trello/integration", methods=["GET"])
@login_required
def integrate_trello():
    authorize_form = AuthorizeTrelloForm()
    return render_template("integrate_trello.html", authorize_form=authorize_form)


@main_blueprint.route("/trello/integration/authorize", methods=["POST"])
@login_required
def authorize_trello():
    if current_user.trello_token:
        abort(400, "Already have an integration token for Trello")

    personalized_authorize_url = (
        "{authorize_url}?expiration={expiration}&scope={scope}&name={name}&response_type=token&key={key}"
    ).format(authorize_url=TRELLO_AUTHORIZE_URL, **TRELLO_TOKEN_SETTINGS)
    return redirect(personalized_authorize_url)


@main_blueprint.route("/trello/integration/complete", methods=["POST"])
@login_required
def authorize_trello_complete():
    form = AuthorizeTrelloForm()

    if form.validate_on_submit():
        if current_user.trello_token:
            abort(400, "Already have an integration token for Trello")

        current_user.trello_token = form.trello_integration.data
        db.session.add(current_user)
        db.session.commit()

        flash("Authorization complete.", "info")
        return redirect(url_for(".dashboard"))

    flash("Form submit failed", "error")
    return redirect(url_for(".index"))


@main_blueprint.route("/trello/revoke", methods=["POST"])
@login_required
def revoke_trello():
    trello_client = get_trello_client(current_user)
    if trello_client.revoke_integration() is False:
        flash(
            "Something went wrong revoking your Trello integration. Please do it directly from your Trello account.",
            "error",
        )

    current_user.trello_token = None
    db.session.add(current_user)
    db.session.commit()

    return redirect(url_for(".dashboard"))


@main_blueprint.route("/trello/choose-board", methods=["GET", "POST"])
@login_required
def trello_choose_board():
    trello_client = get_trello_client(current_user)
    board_form = ChooseTrelloBoardForm(trello_client.get_boards())

    if board_form.validate_on_submit():
        return redirect(url_for(".trello_choose_list", board_id=board_form.board_choice.data))

    return render_template("select-board.html", board_form=board_form)


@main_blueprint.route("/signoff/choose-list", methods=["GET", "POST"])
@login_required
def trello_choose_list():
    if "board_id" not in request.args:
        flash("Please select a Trello board.")
        return redirect(".trello_choose_board")

    trello_client = get_trello_client(current_user)

    list_form = ChooseTrelloListForm(trello_client.get_lists(board_id=request.args["board_id"]))

    if list_form.validate_on_submit():
        try:
            trello_hook = trello_client.create_webhook(
                object_id=list_form.list_choice.data, callback_url=f"{url_for('.trello_callback', _external=True)}"
            )

        except HookAlreadyExists:
            pass

        else:
            trello_list = TrelloList(
                list_id=list_form.list_choice.data, hook_id=trello_hook["id"], user_id=current_user.id
            )
            db.session.add(trello_list)
            db.session.commit()

        list_choices = dict(list_form.list_choice.choices)  # refactor

        flash(
            (
                f"Product signoff will be updated on GitHub when tickets move into the "
                f"“{list_choices.get(list_form.list_choice.data)}” your product signoff integration."
            ),
            "info",
        )
        return redirect(url_for(".dashboard"))

    return render_template("select-list.html", list_form=list_form)
