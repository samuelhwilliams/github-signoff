from functools import wraps
import hashlib
import hmac
import json
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
from flask_breadcrumbs import register_breadcrumb, default_breadcrumb_root
from flask_login import LoginManager, current_user, login_required
from flask_mail import Message
import requests
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import or_

from notifications_python_client.notifications import NotificationsAPIClient

from app import db, mail, sparkpost
from app.auth import login_user, logout_user, new_login_token_and_payload
from app.errors import (
    GithubUnauthorized,
    HookAlreadyExists,
    TrelloUnauthorized,
    TrelloResourceMissing,
    GithubResourceMissing,
)
from app.forms import (
    AuthorizeTrelloForm,
    ChooseGithubRepoForm,
    ChooseTrelloBoardForm,
    ChooseTrelloListForm,
    DeleteAccountForm,
    DeleteProductSignoffForm,
    LoginForm,
    LoginWithPayloadForm,
    ToggleChecklistFeatureForm,
    TransferGithubRepoForm,
)
from app.github import GithubClient
from app.models import (
    GithubRepo,
    LoginToken,
    TrelloBoard,
    TrelloCard,
    TrelloList,
    User,
    GithubIntegration,
    TrelloIntegration,
    ProductSignoff,
)
from app.trello import TrelloClient
from app.updater import Updater
from app.utils import get_github_client, get_trello_client, get_github_token_status, get_trello_token_status


main_blueprint = Blueprint("main", "main")
default_breadcrumb_root(main_blueprint, ".")


@main_blueprint.errorhandler(TrelloUnauthorized)
def trello_unauthorized_handler(error):
    flash(f"Invalid authorisation with Trello: {str(error)}", "warning")

    return redirect(url_for(".dashboard"))


@main_blueprint.errorhandler(GithubUnauthorized)
def github_unauthorized_handler(error):
    flash(f"Invalid authorisation with GitHub: {str(error)}", "warning")
    return redirect(url_for(".dashboard"))


def require_missing_or_invalid_trello_token(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if get_trello_token_status(current_app, current_user) != "valid":
            return func(*args, **kwargs)

        flash("You already have a valid Trello token", "warning")
        return redirect(url_for(".dashboard"))

    return wrapper


def require_missing_or_invalid_github_token(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if get_github_token_status(current_app, current_user) != "valid":
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
            "email/login-link.html", login_link=url_for(".login_with_payload", payload=payload, _external=True)
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
    login_with_payload_form = LoginWithPayloadForm()
    if login_with_payload_form.validate_on_submit():
        user = login_user(current_app, db, payload)
        if user:
            return redirect(url_for(".dashboard"))

    return render_template("auth/login-with-payload.html", login_with_payload_form=login_with_payload_form)


@main_blueprint.route("/logout")
@login_required
def logout():
    logout_user(db)
    flash("You have been logged out.", "info")
    return redirect(url_for(".start_page"))


@main_blueprint.route("/dashboard")
@register_breadcrumb(main_blueprint, ".", "Powerup dashboard")
@login_required
def dashboard():
    github_status = get_github_token_status(current_app, current_user)
    trello_status = get_trello_token_status(current_app, current_user)

    github_repos = (
        GithubRepo.query.filter(GithubRepo.integration == current_user.github_integration).all()
        if github_status == "valid"
        else []
    )

    product_signoffs = (
        ProductSignoff.query.filter(ProductSignoff.user == current_user).all() if trello_status == "valid" else []
    )

    return render_template(
        "dashboard.html",
        github_status=github_status,
        trello_status=trello_status,
        github_repos=github_repos,
        product_signoffs=product_signoffs,
    )


@main_blueprint.route("/account")
@register_breadcrumb(main_blueprint, ".account", "Your account")
@login_required
def account():
    github_status = get_github_token_status(current_app, current_user)
    trello_status = get_trello_token_status(current_app, current_user)

    return render_template("user/account.html", github_status=github_status, trello_status=trello_status)


@main_blueprint.route("/account/delete", methods=["GET", "POST"])
@register_breadcrumb(main_blueprint, ".account.delete_account", "Delete your account")
@login_required
def delete_account():
    delete_account_form = DeleteAccountForm()
    if delete_account_form.validate_on_submit():
        github_status = get_github_token_status(current_app, current_user)
        if github_status == "valid":
            github_client = get_github_client(current_app, current_user)

            for github_repo in GithubRepo.query.filter(GithubRepo.integration == current_user.github_integration).all():
                try:
                    github_client.delete_webhook(github_repo.id, github_repo.hook_id)
                except GithubResourceMissing:
                    pass

            github_client.revoke_integration()

        trello_status = get_trello_token_status(current_app, current_user)
        if trello_status == "valid":
            trello_client = get_trello_client(current_app, current_user)
            trello_client.revoke_integration()

        db.session.delete(current_user)
        db.session.commit()
        session.clear()

        flash("Your account and all authorisations have been deleted.", "warning")
        return redirect(url_for(".start_page"))

    elif delete_account_form.errors:
        for error in delete_account_form.errors.items():
            flash(error, "warning")

    return render_template("user/delete-account.html", delete_account_form=delete_account_form)


@main_blueprint.route("/github/integration", methods=["GET", "POST"])
@register_breadcrumb(main_blueprint, ".integrate_github", "Create authorisation for GitHub")
@login_required
@require_missing_or_invalid_github_token
def integrate_github():
    if request.method == "POST":
        if not current_user.github_integration:
            current_user.github_integration = GithubIntegration()

        current_user.github_integration.oauth_state = str(uuid.uuid4())
        db.session.add(current_user)
        db.session.commit()

        return redirect(
            current_app.config["GITHUB_OAUTH_URL"].format(
                redirect_uri=url_for(".authorize_github_complete", _external=True),
                state=current_user.github_integration.oauth_state,
                **current_app.config["GITHUB_OAUTH_SETTINGS"],
            )
        )

    return render_template("integration/github.html")


@main_blueprint.route("/github/integration/callback", methods=["POST"])
def github_callback():
    if request.headers["X-GitHub-Event"] == "ping":
        return jsonify(status="OK"), 200

    current_app.logger.info(f"Incoming github payload: {request.json}")

    # if "unique_slug" not in request.args or "pull_request" not in request.json:  # TODO: should be abstracted somehow
    #     current_app.logger.info("Missing ‘unique_slug’ in query params or ‘pull_request’ in payload")
    #     return jsonify(status="OK"), 200

    payload = request.json["pull_request"]
    repo_id = payload["head"]["repo"]["id"]

    github_repo = GithubRepo.query.get(repo_id)
    if not github_repo:
        current_app.logger.info("No github_repo found in database")
        return jsonify(status="GONE"), 410

    # if github_repo.hook_unique_slug != request.args["unique_slug"]:
    #     current_app.logger.info("Mis-match on hook’s unique slug")
    #     return jsonify(status="BAD SLUG"), 400

    # verify_signature = (
    #     "sha1=" + hmac.new(github_repo.hook_secret.encode("utf8"), request.data, hashlib.sha1).hexdigest()
    # )
    # if not hmac.compare_digest(request.headers["X-Hub-Signature"], verify_signature):
    #     current_app.logger.info("X-Hub-Signature verification failed")
    #     return jsonify(status="OK"), 200

    updater = Updater(current_app, db, github_repo.integration.user)
    updater.sync_pull_request(data=payload)

    return jsonify(status="OK"), 200


@main_blueprint.route("/github/integration/complete")
@login_required
@require_missing_or_invalid_github_token
def authorize_github_complete():
    if request.args["state"] != current_user.github_integration.oauth_state:
        flash("Invalid state from GitHub authentication. Possible man-in-the-middle attempt. Process aborted.")
        return redirect(url_for(".dashboard"))

    response = requests.get(
        current_app.config["GITHUB_TOKEN_URL"],
        params={
            "client_id": current_app.config["GITHUB_CLIENT_ID"],
            "client_secret": current_app.config["GITHUB_CLIENT_SECRET"],
            "code": request.args["code"],
            "state": current_user.github_integration.oauth_state,
        },
        headers={"Accept": "application/json"},
    )

    if response.status_code == 200:
        current_user.github_integration.oauth_token = response.json()["access_token"]

        github_client = get_github_client(current_app, current_user)
        if github_client.is_token_valid():
            db.session.add(current_user)
            db.session.commit()

            flash("GitHub authorisation successful.", "info")
            return redirect(url_for(".dashboard"))

    flash("The GitHub authorisation token you have submitted is invalid. Please try again.", "warning")
    return render_template(url_for(".integrate_github"))


@main_blueprint.route("/github/choose-repos", methods=["GET", "POST"])
@register_breadcrumb(main_blueprint, ".github_choose_repos", "Choose repositories")
@login_required
def github_choose_repos():
    github_client = get_github_client(current_app, current_user)
    available_repos = github_client.get_repos()
    print("available_repos", available_repos)
    editable_repos = [
        repo
        for repo in available_repos
        if (not repo.integration) or repo.integration == current_user.github_integration
    ]
    editable_repo_ids = {repo.id for repo in editable_repos}
    print("editable_repos", editable_repos)
    owned_by_another_repos = [
        repo for repo in available_repos if repo.integration and repo.integration != current_user.github_integration
    ]
    owned_by_another_repo_ids = {repo.id for repo in owned_by_another_repos}
    print("owned_by_another_repos", owned_by_another_repos)

    repo_form = ChooseGithubRepoForm(editable_repos)

    if repo_form.validate_on_submit():
        github_client = get_github_client(current_app, current_user)
        chosen_repo_ids = editable_repo_ids.intersection(set(repo_form.repo_choice.data)) - owned_by_another_repo_ids

        updater = Updater(current_app, db, current_user)
        updater.sync_repositories(chosen_repo_ids)

        return redirect(url_for(".dashboard"))

    elif repo_form.errors:
        for error in repo_form.errors.items():
            flash(error, "warning")

    existing_repos = GithubRepo.query.filter(GithubRepo.id.in_([repo.id for repo in editable_repos])).all()
    repo_form.repo_choice.data = [repo.id for repo in existing_repos]

    return render_template(
        "integration/choose-repos.html", repo_form=repo_form, owned_by_another_repos=owned_by_another_repos
    )


@main_blueprint.route("/github/transfer-existing-repos", methods=["GET", "POST"])
@register_breadcrumb(
    main_blueprint, ".github_choose_repos.github_transfer_existing_repos", "Transfer connected repositories"
)
@login_required
def github_transfer_existing_repos():
    github_client = get_github_client(current_app, current_user)
    available_repos = github_client.get_repos()
    repos_owned_by_another = [
        repo for repo in available_repos if repo.integration and repo.integration != current_user.github_integration
    ]

    repo_form = TransferGithubRepoForm(repos_owned_by_another)

    if repo_form.validate_on_submit():
        github_client = get_github_client(current_app, current_user)
        chosen_repo_id = repo_form.repo_choice.data

        updater = Updater(current_app, db, current_user)
        updater.transfer_repository(chosen_repo_id)

        return redirect(url_for(".dashboard"))

    elif repo_form.errors:
        for error in repo_form.errors.items():
            flash(error, "warning")

    return render_template("integration/transfer-existing-repos.html", repo_form=repo_form)


@main_blueprint.route("/github/revoke", methods=["POST"])
@login_required
def revoke_github():
    github_client = get_github_client(current_app, current_user)

    if github_client.is_token_valid():
        for github_repo in GithubRepo.query.filter(GithubRepo.integration == current_user.github_integration).all():
            try:
                github_client.delete_webhook(github_repo.id, github_repo.hook_id)
            except GithubResourceMissing:
                pass

        if github_client.revoke_integration() is False:
            flash(
                (
                    "Something went wrong revoking your GitHub authorisation. Please revoke it directly from "
                    "https://github.com/settings/applications"
                ),
                "error",
            )
            return redirect(url_for(".dashboard"))

    db.session.delete(current_user.github_integration)
    db.session.commit()

    flash("GitHub authorisation token revoked successfully.")

    return redirect(url_for(".dashboard"))


@main_blueprint.route("/trello/integration", methods=["HEAD"])
def integrate_trello_head():
    return jsonify(status="OK"), 200


@main_blueprint.route("/trello/integration", methods=["POST"])
def trello_callback():
    data = json.loads(request.get_data(as_text=True))
    current_app.logger.debug(f"Incoming trello payload: {data}")
    if data.get("action", {}).get("type") == "updateCard":
        trello_card = TrelloCard.from_json(data["action"]["data"]["card"])
        if trello_card and trello_card.pull_requests:
            updater = Updater(current_app, db, trello_card.pull_requests[0].repo.integration.user)
            updater.sync_trello_card(trello_card)
        
    else:
        current_app.logger.debug("Ignoring payload: not an `updateCard`")

    return jsonify(status="OK"), 200


@main_blueprint.route("/trello/integration", methods=["GET"])
@register_breadcrumb(main_blueprint, ".integrate_trello", "Create authorisation for Trello")
@login_required
@require_missing_or_invalid_trello_token
def integrate_trello():
    authorize_form = AuthorizeTrelloForm()
    return render_template("integration/trello.html", authorize_form=authorize_form)


@main_blueprint.route("/trello/integration/authorise", methods=["POST"])
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
        current_user.trello_integration = TrelloIntegration(oauth_token=authorize_form.trello_integration.data)

        trello_client = get_trello_client(current_app, current_user)
        if trello_client.is_token_valid():
            db.session.add(current_user)
            db.session.commit()

            flash("Trello authorisation successful.", "info")
            return redirect(url_for(".dashboard"))

        flash("The Trello authorisation token you have submitted is invalid. Please try again.", "warning")
        return render_template("integrate-trello.html", authorize_form=authorize_form)

    flash("Form submit failed", "error")
    return redirect(url_for(".start_page"))


@main_blueprint.route("/trello/revoke", methods=["POST"])
@login_required
def revoke_trello():
    trello_client = get_trello_client(current_app, current_user)
    if trello_client.revoke_integration() is False:
        flash(
            "Something went wrong revoking your Trello authorisation. Please do it directly from your Trello account.",
            "error",
        )

    db.session.delete(current_user.trello_integration)
    db.session.commit()

    flash("Trello authorisation token revoked successfully.")

    return redirect(url_for(".dashboard"))


@main_blueprint.route("/trello/product-signoff")
@register_breadcrumb(main_blueprint, ".trello_product_signoff", "Product sign-off checks")
@login_required
def trello_product_signoff():
    trello_client = get_trello_client(current_app, current_user)
    all_trello_boards_json = trello_client.get_boards(with_lists=True, as_json=True)
    all_trello_boards_by_id = {board_json["id"]: board_json for board_json in all_trello_boards_json}

    existing_product_signoff_checks = ProductSignoff.query.filter(
        ProductSignoff.trello_board.has(TrelloBoard.id.in_(all_trello_boards_by_id.keys()))
    ).all()

    for product_signoff in existing_product_signoff_checks:
        product_signoff.hydrate_from_board_json(all_trello_boards_by_id[product_signoff.trello_board.id])

    return render_template(
        "features/signoff/product-signoff.html",
        existing_product_signoff_checks=existing_product_signoff_checks,
        can_connect_more_boards=len(all_trello_boards_json) > len(existing_product_signoff_checks),
    )


def get_board_name(*args, **kwargs):
    signoff_id = request.view_args["signoff_id"]
    product_signoff = ProductSignoff.query.filter(ProductSignoff.id == signoff_id).one()
    trello_client = get_trello_client(current_app, current_user)
    board = trello_client.get_board(product_signoff.trello_board_id)
    return [{"text": board.name, "url": url_for(".trello_manage_product_signoff", signoff_id=signoff_id)}]


@main_blueprint.route("/trello/product-signoff/<signoff_id>")
@register_breadcrumb(
    main_blueprint, ".trello_product_signoff.trello_manage_product_signoff", "", dynamic_list_constructor=get_board_name)
@login_required
def trello_manage_product_signoff(signoff_id):
    trello_client = get_trello_client(current_app, current_user)
    product_signoff = ProductSignoff.query.filter(
        ProductSignoff.id == signoff_id
    ).one_or_none()
    if not product_signoff:
        flash("No such board")
        return redirect(url_for(".trello_product_signoff")), 404

    elif product_signoff.user != current_user:
        flash("That product signoff check is owned by another person")
        return redirect(url_for(".trello_product_signoff")), 403

    product_signoff.hydrate(trello_client)

    return render_template("features/signoff/manage-product-signoff.html", product_signoff=product_signoff)


@main_blueprint.route("/trello/product-signoff/<signoff_id>/delete", methods=["GET", "POST"])
@register_breadcrumb(
    main_blueprint, ".trello_product_signoff.trello_manage_product_signoff.trello_delete_signoff_check", "Delete check"
)
@login_required
def trello_delete_signoff_check(signoff_id):
    delete_product_signoff_form = DeleteProductSignoffForm()

    trello_client = get_trello_client(current_app, current_user)

    product_signoff = ProductSignoff.query.filter(
        ProductSignoff.id == signoff_id
    ).one_or_none()
    if not product_signoff:
        flash("No such product signoff")
        return redirect(url_for(".trello_product_signoff")), 404

    elif product_signoff.user != current_user:
        flash("That product signoff check is owned by another person")
        return redirect(url_for(".trello_product_signoff")), 403

    product_signoff.hydrate(trello_client)

    if delete_product_signoff_form.validate_on_submit():
        try:
            trello_client.delete_webhook(product_signoff.trello_list.hook_id)

        except TrelloResourceMissing:
            pass

        flash(
            f"You have deleted the product sign-off check on the ‘{product_signoff.trello_board.name}’ board.",
            "warning",
        )
        db.session.delete(product_signoff)
        db.session.commit()

        return redirect(url_for(".trello_product_signoff"))

    elif delete_product_signoff_form.errors:
        for error in delete_product_signoff_form.errors.items():
            flash(error, "warning")

    return render_template(
        "features/signoff/delete-product-signoff.html",
        delete_product_signoff_form=delete_product_signoff_form,
        product_signoff=product_signoff,
    )


@main_blueprint.route("/trello/choose-board", methods=["GET", "POST"])
@register_breadcrumb(main_blueprint, ".trello_product_signoff.trello_choose_board", "Choose Trello board")
@login_required
def trello_choose_board():
    trello_client = get_trello_client(current_app, current_user)
    all_trello_boards = trello_client.get_boards(with_lists=True)
    all_trello_boards_by_id = {board.id: board for board in all_trello_boards}

    existing_product_signoff_checks = ProductSignoff.query.filter(
        ProductSignoff.trello_board.has(TrelloBoard.id.in_(all_trello_boards_by_id.keys()))
    ).all()
    existing_trello_board_ids = {product_signoff.trello_board.id for product_signoff in existing_product_signoff_checks}

    available_trello_boards = [board for board in all_trello_boards if board.id not in existing_trello_board_ids]

    board_form = ChooseTrelloBoardForm(available_trello_boards)

    if board_form.validate_on_submit():
        return redirect(url_for(".trello_choose_list", board_id=board_form.board_choice.data))

    elif board_form.errors:
        for error in board_form.errors.items():
            flash(error, "warning")

    return render_template("features/signoff/select-board.html", board_form=board_form)


@main_blueprint.route("/signoff/choose-list", methods=["GET", "POST"])
@register_breadcrumb(main_blueprint, ".trello_product_signoff.trello_choose_list", "Choose Trello list")
@login_required
def trello_choose_list():
    board_id = request.args.get("board_id", None)
    if not board_id:
        flash("Please select a Trello board.")
        return redirect(".trello_choose_board")

    if ProductSignoff.query.filter(ProductSignoff.trello_board.has(TrelloBoard.id == board_id)).count():
        flash("Product sign-off checks are already enabled for that board.", "warning")
        return redirect(url_for(".trello_product_signoff"))

    trello_client = get_trello_client(current_app, current_user)
    trello_lists = trello_client.get_lists(board_id=request.args["board_id"])

    list_form = ChooseTrelloListForm(trello_lists)

    if list_form.validate_on_submit():
        list_id = list_form.list_choice.data
        try:
            trello_hook = trello_client.create_webhook(
                object_id=list_id,
                callback_url="https://github-trello-powerup.herokuapp.com/trello/integration",  # FIXME
            )

        except HookAlreadyExists:
            trello_hook = trello_client.get_webhook(object_id=list_id)

        trello_board = TrelloBoard.from_json(trello_client.get_board(board_id, as_json=True))
        trello_list = TrelloList.from_json(trello_client.get_list(list_id, as_json=True))
        trello_list.hook_id = trello_hook["id"]
        product_signoff = ProductSignoff(user=current_user, trello_board=trello_board, trello_list=trello_list)
        db.session.add(product_signoff)
        db.session.commit()

        flash((f"Product sign-off checks added to the “{trello_board.name}” board."), "info")
        return redirect(url_for(".dashboard"))

    elif list_form.errors:
        for error in list_form.errors.items():
            flash(error, "warning")

    return render_template("features/signoff/select-list.html", list_form=list_form)


@main_blueprint.route("/feature/checklists", methods=["GET", "POST"])
@register_breadcrumb(main_blueprint, ".feature_checklists", "Trello checklists")
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
            flash("Pull requests will automatically be added to Trello cards as checklist items.", "info")

        return redirect(url_for(".dashboard"))

    elif toggle_checklist_feature_form.errors:
        for error in toggle_checklist_feature_form.errors.items():
            flash(error, "warning")

    return render_template(
        "features/checklists/checklists.html", toggle_checklist_feature_form=toggle_checklist_feature_form
    )
