from functools import wraps
import json
import logging
import uuid

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
from flask_mail import Message
import requests
from sqlalchemy.orm.exc import NoResultFound

from notifications_python_client.notifications import NotificationsAPIClient

from app import db, mail, sparkpost
from app.auth import login_user, logout_user, new_login_token_and_payload
from app.errors import GithubUnauthorized, HookAlreadyExists, TrelloUnauthorized, TrelloResourceMissing, GithubResourceMissing
from app.forms import (
    AuthorizeTrelloForm,
    ChooseGithubRepoForm,
    ChooseTrelloBoardForm,
    ChooseTrelloListForm,
    DeleteAccountForm,
    DeleteProductSignoffForm,
    LoginForm,
    ToggleChecklistFeatureForm,
)
from app.github import GithubClient
from app.models import GithubRepo, LoginToken, PullRequestStatus, TrelloCard, TrelloList, User
from app.trello import TrelloClient
from app.updater import Updater
from app.utils import get_github_client, get_trello_client, get_github_token_status, get_trello_token_status


main_blueprint = Blueprint("main", "main")
logger = logging.getLogger(__name__)


@main_blueprint.errorhandler(TrelloUnauthorized)
def trello_unauthorized_handler(error):
    flash(f"Invalid authorization with Trello: {str(error)}", "warning")
    
    return redirect(url_for(".dashboard"))


@main_blueprint.errorhandler(GithubUnauthorized)
def github_unauthorized_handler(error):
    flash(f"Invalid authorization with GitHub: {str(error)}", "warning")
    return redirect(url_for(".dashboard"))


def require_missing_or_invalid_trello_token(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        trello_client = get_trello_client(current_app, current_user)
        if not current_user.trello_token or not trello_client.is_token_valid():
            return func(*args, **kwargs)

        flash("You already have a valid Trello token", "warning")
        return redirect(url_for(".dashboard"))

    return wrapper


def require_missing_or_invalid_github_token(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        github_client = get_github_client(current_app, current_user)
        if not current_user.github_token or not github_client.is_token_valid():
            return func(*args, **kwargs)

        flash("You already have a valid GitHub token", "warning")
        return redirect(url_for(".dashboard"))

    return wrapper


@main_blueprint.route("/", methods=["GET", "POST"])
def start_page():
    if request.method == "GET" and current_user.is_authenticated:
        return redirect(url_for(".dashboard"))

    return render_template("public/start-page.html")


@main_blueprint.route("/login", methods=["GET", "POST"])
def login():
    login_form = LoginForm()

    if login_form.validate_on_submit():
        user = User.find_or_create(login_form.email.data)
        if user.active:
            user.active = False
        db.session.add(user)

        token, payload = new_login_token_and_payload(current_app, db, user)
        
        message_body = render_template(
            "email/login-link.html",
            login_link=url_for(".login_with_payload", payload=payload, _external=True)
        )
        
        sparkpost.transmissions.send(
            recipients=[login_form.email.data],
            html=message_body,
            from_email=current_app.config["MAIL_DEFAULT_SENDER"],
            subject=f"Login to {current_app.config['APP_NAME']}",
        )

        # message = Message(
        #     f"Login to {current_app.config['APP_NAME']}",
        #     sender=current_app.config["MAIL_DEFAULT_SENDER"],
        #     recipients=[login_form.email.data],
        # )
        # message.html = render_template(
        #     "email/login-link.html", login_link=url_for(".login_with_payload", payload=payload, _external=True)
        # )

        # mail.send(message)

        # notifications_client = NotificationsAPIClient(current_app.config["NOTIFY_API_KEY"])
        # notifications_client.send_email_notification(
        #     email_address=login_form.email.data,
        #     template_id=current_app.config["NOTIFY_TEMPLATE_LOGIN_LINK"],
        #     personalisation={"login_link": url_for(".login_with_payload", payload=payload, _external=True)},
        # )

        print(message_body)

        db.session.commit()

        return render_template("auth/login-sent.html", email_address=login_form.email.data)

    return render_template("auth/login.html", login_form=login_form)


@main_blueprint.route("/login/<payload>", methods=["GET", "POST"])
def login_with_payload(payload):
    user = login_user(current_app, db, payload)
    if user:
        return redirect(url_for(".dashboard"))

    return redirect(url_for(".start_page"))


@main_blueprint.route("/logout")
@login_required
def logout():
    logout_user(db)
    flash("You have been logged out.", "info")
    return redirect(url_for(".start_page"))


@main_blueprint.route("/dashboard")
@login_required
def dashboard():
    github_status = get_github_token_status(current_app, current_user)
    trello_status = get_trello_token_status(current_app, current_user)

    github_repos = (
        GithubRepo.query.filter(GithubRepo.user_id == current_user.id).all() if github_status == "valid" else []
    )

    trello_lists = (
        TrelloList.query.filter(TrelloList.user_id == current_user.id).all() if trello_status == "valid" else []
    )

    return render_template(
        "dashboard.html",
        github_status=github_status,
        trello_status=trello_status,
        github_repos=github_repos,
        trello_lists=trello_lists,
    )


@main_blueprint.route("/account")
@login_required
def account():
    github_status = get_github_token_status(current_app, current_user)
    trello_status = get_trello_token_status(current_app, current_user)

    return render_template("user/account.html", github_status=github_status, trello_status=trello_status)


@main_blueprint.route("/account/delete", methods=["GET", "POST"])
@login_required
def delete_account():
    delete_account_form = DeleteAccountForm()
    if delete_account_form.validate_on_submit():
        if current_user.github_token:
            github_client = get_github_client(current_app, current_user)

            if github_client.is_token_valid():
                for github_repo in GithubRepo.query.filter(GithubRepo.user_id == current_user.id).all():
                    try:
                        github_client.delete_webhook(github_repo.fullname, github_repo.hook_id)
                    except GithubResourceMissing:
                        pass

                github_client.revoke_integration()

        if current_user.trello_token:
            trello_client = get_trello_client(current_app, current_user)
            if trello_client.is_token_valid():
                trello_client.revoke_integration()

        db.session.delete(current_user)
        db.session.commit()
        session.clear()

        flash("Your account and all authorizations have been deleted.", "warning")
        return redirect(url_for(".start_page"))

    elif delete_account_form.errors:
        for error in delete_account_form.errors.items():
            flash(error, "warning")

    return render_template("user/delete-account.html", delete_account_form=delete_account_form)


@main_blueprint.route("/github/integration", methods=["GET", "POST"])
@login_required
@require_missing_or_invalid_github_token
def integrate_github():
    if request.method == "POST":
        current_user.github_state = str(uuid.uuid4())
        db.session.add(current_user)
        db.session.commit()

        return redirect(
            current_app.config["GITHUB_OAUTH_URL"].format(
                redirect_uri=url_for(".authorize_github_complete", _external=True),
                state=current_user.github_state,
                **current_app.config["GITHUB_OAUTH_SETTINGS"],
            )
        )

    return render_template("integration/github.html")


@main_blueprint.route("/github/integration/callback", methods=["POST"])
def github_callback():
    if request.headers["X-GitHub-Event"] == "ping":
        return jsonify(status="OK"), 200
    
    print("Incoming github payload: ", request.json)

    payload = request.json["pull_request"]
    repo_id = payload["head"]["repo"]["id"]
    
    github_repo = GithubRepo.query.get(repo_id)
    if not github_repo:
        logger.warning(f"Callback received but no repository registered in database: {repo_id}")
        return jsonify(status="OK"), 200

    updater = Updater(current_app, db, github_repo.user)
    updater.sync_pull_request(user=github_repo.user, data=payload)

    return jsonify(status="OK"), 200


@main_blueprint.route("/github/integration/complete")
@login_required
@require_missing_or_invalid_github_token
def authorize_github_complete():
    if request.args["state"] != current_user.github_state:
        flash("Invalid state from GitHub authentication. Possible man-in-the-middle attempt. Process aborted.")
        return redirect(url_for(".dashboard"))

    response = requests.get(
        current_app.config["GITHUB_TOKEN_URL"],
        params={
            "client_id": current_app.config["GITHUB_CLIENT_ID"],
            "client_secret": current_app.config["GITHUB_CLIENT_SECRET"],
            "code": request.args["code"],
            "state": current_user.github_state,
        },
        headers={"Accept": "application/json"},
    )

    if response.status_code == 200:
        current_user.github_token = response.json()["access_token"]

        github_client = get_github_client(current_app, current_user)
        if github_client.is_token_valid():
            db.session.add(current_user)
            db.session.commit()

            flash("GitHub authorization successful.", "info")
            return redirect(url_for(".dashboard"))

    flash("The GitHub authorization token you have submitted is invalid. Please try again.", "warning")
    return render_template(url_for(".integrate_github"))


@main_blueprint.route("/github/choose-repos", methods=["GET", "POST"])
@login_required
def github_choose_repos():
    github_client = get_github_client(current_app, current_user)
    repo_form = ChooseGithubRepoForm(github_client.get_repos())

    if repo_form.validate_on_submit():
        github_client = get_github_client(current_app, current_user)
        chosen_repo_ids = set(repo_form.repo_choice.data)

        updater = Updater(current_app, db, current_user)
        updater.sync_repositories(chosen_repo_ids)

        return redirect(url_for(".dashboard"))
    
    elif repo_form.errors:
        for error in repo_form.errors.items():
            flash(error, "warning")

    existing_repos = GithubRepo.query.filter(GithubRepo.user_id == current_user.id).all()
    repo_form.repo_choice.data = [repo.id for repo in existing_repos]

    return render_template("integration/select-repos.html", repo_form=repo_form)


@main_blueprint.route("/github/revoke", methods=["POST"])
@login_required
def revoke_github():
    github_client = get_github_client(current_app, current_user)

    if github_client.is_token_valid():
        for github_repo in GithubRepo.query.filter(GithubRepo.user_id == current_user.id).all():
            try:
                github_client.delete_webhook(github_repo.fullname, github_repo.hook_id)
            except GithubResourceMissing:
                pass

        if github_client.revoke_integration() is False:
            flash(
                (
                    "Something went wrong revoking your GitHub authorization. Please revoke it directly from "
                    "https://github.com/settings/applications"
                ),
                "error",
            )
            return redirect(url_for(".dashboard"))

    current_user.github_token = None
    current_user.github_state = None
    db.session.add(current_user)
    db.session.commit()

    flash("GitHub authorization token revoked successfully.")

    return redirect(url_for(".dashboard"))


@main_blueprint.route("/trello/integration", methods=["HEAD"])
def integrate_trello_head():
    return jsonify(status="OK"), 200


@main_blueprint.route("/trello/integration", methods=["POST"])
def trello_callback():
    data = json.loads(request.get_data(as_text=True))
    print("Incoming trello payload: ", data)
    if data.get("action", {}).get("type") == "updateCard":
        trello_card = TrelloCard.from_json(data["action"]["data"]["card"])
        if trello_card and trello_card.pull_requests:
            updater = Updater(current_app, db, trello_card.pull_requests[0].user)
            updater.sync_trello_card(trello_card)

    return jsonify(status="OK"), 200


@main_blueprint.route("/trello/integration", methods=["GET"])
@login_required
@require_missing_or_invalid_trello_token
def integrate_trello():
    authorize_form = AuthorizeTrelloForm()
    return render_template("integration/trello.html", authorize_form=authorize_form)


@main_blueprint.route("/trello/integration/authorize", methods=["POST"])
@login_required
@require_missing_or_invalid_trello_token
def authorize_trello():
    personalized_authorize_url = (
        "{authorize_url}?expiration={expiration}&scope={scope}&name={name}&response_type=token&key={key}"
    ).format(authorize_url=current_app.config["TRELLO_AUTHORIZE_URL"], **current_app.config["TRELLO_TOKEN_SETTINGS"])
    return redirect(personalized_authorize_url)


@main_blueprint.route("/trello/integration/complete", methods=["POST"])
@login_required
@require_missing_or_invalid_trello_token
def authorize_trello_complete():
    authorize_form = AuthorizeTrelloForm()

    if authorize_form.validate_on_submit():
        current_user.trello_token = authorize_form.trello_integration.data

        trello_client = get_trello_client(current_app, current_user)
        if trello_client.is_token_valid():
            # Delete any lists from a user's old/expired/revoked tokens
            TrelloList.query.filter(TrelloList.user == current_user).delete()
            
            db.session.add(current_user)
            db.session.commit()

            flash("Trello authorization successful.", "info")
            return redirect(url_for(".dashboard"))

        flash("The Trello authorization token you have submitted is invalid. Please try again.", "warning")
        return render_template("integrate-trello.html", authorize_form=authorize_form)

    flash("Form submit failed", "error")
    return redirect(url_for(".start_page"))


@main_blueprint.route("/trello/revoke", methods=["POST"])
@login_required
def revoke_trello():
    trello_client = get_trello_client(current_app, current_user)
    if trello_client.revoke_integration() is False:
        flash(
            "Something went wrong revoking your Trello authorization. Please do it directly from your Trello account.",
            "error",
        )

    current_user.trello_token = None
    db.session.add(current_user)
    db.session.commit()

    flash("Trello authorization token revoked successfully.")

    return redirect(url_for(".dashboard"))


@main_blueprint.route("/trello/product-signoff")
@login_required
def trello_product_signoff():
    trello_client = get_trello_client(current_app, current_user)
    trello_lists = [
        l.hydrate(trello_client=trello_client)
        for l in TrelloList.query.filter(TrelloList.user_id == current_user.id).all()
    ]
    trello_boards_and_lists = {trello_client.get_board(l.board_id): l for l in trello_lists}
    return render_template("features/signoff/product-signoff.html", trello_boards_and_lists=trello_boards_and_lists)


@main_blueprint.route("/trello/product-signoff/<board_id>")
@login_required
def trello_manage_product_signoff(board_id):
    trello_client = get_trello_client(current_app, current_user)
    trello_board = trello_client.get_board(board_id)
    trello_lists = trello_client.get_lists(trello_board.board_id)
    trello_list = TrelloList.query.filter(TrelloList.id.in_([l.id for l in trello_lists])).one()
    trello_list.hydrate(trello_client=trello_client)

    return render_template(
        "features/signoff/manage-product-signoff.html", trello_board=trello_board, trello_list=trello_list
    )


@main_blueprint.route("/trello/product-signoff/<board_id>/delete", methods=["GET", "POST"])
@login_required
def trello_delete_signoff_check(board_id):
    delete_product_signoff_form = DeleteProductSignoffForm()

    trello_client = get_trello_client(current_app, current_user)
    trello_board = trello_client.get_board(board_id)

    if delete_product_signoff_form.validate_on_submit():
        trello_lists = trello_client.get_lists(trello_board.board_id)
        trello_list = TrelloList.query.filter(TrelloList.id.in_([l.id for l in trello_lists])).one()

        try:
            trello_client.delete_webhook(trello_list.hook_id)
        except TrelloResourceMissing:
            pass

        db.session.delete(trello_list)
        db.session.commit()

        flash(f"You have deleted the product sign-off check on the ‘{trello_board.name}’ board.", "warning")
        return redirect(url_for(".trello_product_signoff"))

    elif delete_product_signoff_form.errors:
        for error in delete_product_signoff_form.errors.items():
            flash(error, "warning")

    return render_template(
        "features/signoff/delete-product-signoff.html",
        delete_product_signoff_form=delete_product_signoff_form,
        trello_board=trello_board,
    )


@main_blueprint.route("/trello/choose-board", methods=["GET", "POST"])
@login_required
def trello_choose_board():
    trello_client = get_trello_client(current_app, current_user)
    trello_boards = trello_client.get_boards()
    existing_trello_boards = {
        trello_client.get_list(l.id).board_id
        for l in TrelloList.query.filter(TrelloList.user_id == current_user.id).all()
    }

    trello_boards = list(filter(lambda x: x.board_id not in existing_trello_boards, trello_boards))

    board_form = ChooseTrelloBoardForm(trello_boards)

    if board_form.validate_on_submit():
        return redirect(url_for(".trello_choose_list", board_id=board_form.board_choice.data))

    elif board_form.errors:
        for error in board_form.errors.items():
            flash(error, "warning")

    return render_template("features/signoff/select-board.html", board_form=board_form)


@main_blueprint.route("/signoff/choose-list", methods=["GET", "POST"])
@login_required
def trello_choose_list():
    if "board_id" not in request.args:
        flash("Please select a Trello board.")
        return redirect(".trello_choose_board")

    trello_client = get_trello_client(current_app, current_user)

    trello_lists_for_board = trello_client.get_lists(board_id=request.args["board_id"])
    if TrelloList.query.filter(TrelloList.id.in_([l.id for l in trello_lists_for_board])).first():
        flash("Product sign-off checks are already enabled for that board.", "warning")
        return redirect(url_for(".trello_product_signoff"))

    list_form = ChooseTrelloListForm(trello_client.get_lists(board_id=request.args["board_id"]))

    if list_form.validate_on_submit():
        list_choices = dict(list_form.list_choice.choices)  # refactor
        try:
            trello_hook = trello_client.create_webhook(
                object_id=list_form.list_choice.data, callback_url=f"{url_for('.trello_callback', _external=True)}"
            )

        except HookAlreadyExists:
            pass

        else:
            trello_list = TrelloList(id=list_form.list_choice.data, hook_id=trello_hook["id"], user_id=current_user.id)
            db.session.add(trello_list)
            db.session.commit()

        flash((f"Product sign-off checks added to the “{list_choices.get(list_form.list_choice.data)}” board."), "info")
        return redirect(url_for(".trello_product_signoff"))

    elif list_form.errors:
        for error in list_form.errors.items():
            flash(error, "warning")

    return render_template("features/signoff/select-list.html", list_form=list_form)


@main_blueprint.route("/feature/checklists", methods=["GET", "POST"])
@login_required
def feature_checklists():
    toggle_checklist_feature_form = ToggleChecklistFeatureForm()

    if toggle_checklist_feature_form.validate_on_submit():
        feature_enabled = current_user.checklist_feature_enabled
        current_user.checklist_feature_enabled = not feature_enabled
        db.session.add(current_user)
        db.session.commit()

        if feature_enabled:
            flash("Pull requests will no longer be attached to Trello cards as checklist items.", "warning")

        else:
            flash("Pull requests which now automatically be added to Trello cards as checklist items.", "info")

        return redirect(url_for(".dashboard"))

    elif toggle_checklist_feature_form.errors:
        for error in toggle_checklist_feature_form.errors.items():
            flash(error, "warning")

    return render_template(
        "features/checklists/checklists.html", toggle_checklist_feature_form=toggle_checklist_feature_form
    )
