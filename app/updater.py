import uuid
from secrets import token_urlsafe

from flask import flash, url_for, render_template

from app import db, sparkpost
from app.constants import AWAITING_PRODUCT_REVIEW, TICKET_APPROVED_BY, StatusEnum
from app.errors import TrelloInvalidRequest, TrelloResourceMissing, GithubResourceMissing, GithubUnauthorized
from app.models import (
    GithubRepo,
    TrelloCard,
    TrelloList,
    TrelloChecklist,
    TrelloCheckitem,
    PullRequest,
    ProductSignoff,
    TrelloBoard,
)
from app.utils import get_github_client, get_trello_client, get_trello_cards_from_text


class Updater:
    def __init__(self, app, db, user):
        self.app = app
        self.db = db
        self.user = user
        self.github_client = get_github_client(app, user)
        self.trello_client = get_trello_client(app, user)

    def _set_pull_request_status(self, pull_request, status):
        description = TICKET_APPROVED_BY if status == StatusEnum.SUCCESS.value else AWAITING_PRODUCT_REVIEW
        response = self.github_client.set_pull_request_status(
            statuses_url=pull_request.statuses_url,
            status=status,
            description=description,
            context=self.app.config["APP_NAME"],
        )

        if response.status_code != 201:
            self.app.logger.error(response, response.text)

    def _update_tracked_trello_cards(self, pull_request, new_trello_cards):
        self.app.logger.debug(f"Existing cards: {pull_request.trello_cards}")

        for trello_card in pull_request.trello_cards:
            if trello_card not in new_trello_cards:
                if trello_card.trello_checklist:
                    trello_checkitem = TrelloCheckitem.query.filter(
                        TrelloCheckitem.checklist == trello_card.trello_checklist,
                        TrelloCheckitem.pull_request == pull_request,
                    ).one_or_none()

                    if trello_checkitem:
                        self.trello_client.delete_checkitem(
                            checklist_id=trello_card.trello_checklist.id, checkitem_id=trello_checkitem.id
                        )

                db.session.delete(trello_card)

        pull_request.trello_cards = new_trello_cards

        db.session.add(pull_request)
        db.session.commit()

    def _update_trello_checklists(self, pull_request):
        trello_cards = pull_request.trello_cards
        self.app.logger.debug(f"Updating trello checklists for {pull_request}")
        self.app.logger.debug(f"These cards involvd: {trello_cards}")

        for i, trello_card in enumerate(trello_cards):
            self.app.logger.debug(f"trello card #{i}: {trello_card}")
            trello_card.hydrate(trello_client=self.trello_client)

            trello_checklist = trello_card.trello_checklist
            if trello_checklist:
                try:
                    trello_checklist.hydrate(trello_client=self.trello_client)

                except TrelloResourceMissing:
                    print("resource is missing, yep checklist")
                    if trello_checklist:
                        db.session.delete(trello_checklist)
                        db.session.flush()
                        trello_checklist = None

            if not trello_checklist:
                trello_checklist = self.trello_client.create_checklist(
                    real_card_id=trello_card.real_id, checklist_name=self.app.config["FEATURE_CHECKLIST_NAME"]
                )

            found_trello_checkitem = None
            for trello_checkitem in trello_checklist.trello_checkitems:
                if (
                    trello_checkitem.checklist_id == trello_checklist.id
                    and trello_checkitem.pull_request_id == pull_request.id
                ):
                    found_trello_checkitem = trello_checkitem
                    break

            trello_checkitem = found_trello_checkitem
            if trello_checkitem:
                try:
                    trello_checkitem.hydrate(trello_client=self.trello_client)

                except TrelloResourceMissing:
                    print("resource is missing, yep checkitem")
                    if trello_checkitem:
                        print("deleting")
                        trello_checklist.trello_checkitems.remove(trello_checkitem)
                        db.session.add(trello_checklist)
                        db.session.delete(trello_checkitem)
                        db.session.flush()
                        trello_checkitem = None

            if not trello_checkitem:
                trello_checkitem = self.trello_client.create_checkitem(
                    checklist_id=trello_checklist.id,
                    checkitem_name=pull_request.html_url,
                    checked="true" if pull_request.state == "closed" else "false",
                )
            elif (trello_checkitem.state == "incomplete" and pull_request.state == "closed") or (
                trello_checkitem.state == "complete" and pull_request.state == "open"
            ):
                self.trello_client.update_checkitem(
                    real_card_id=trello_card.real_id,
                    checkitem_id=trello_checkitem.id,
                    state="complete" if pull_request.state == "closed" else "incomplete",
                )

            trello_checklist.card_id = trello_card.id
            trello_checkitem.pull_request_id = pull_request.id
            db.session.add(trello_checklist)
            db.session.add(trello_checkitem)

        db.session.commit()

    def _update_pull_request_status(self, pull_request):
        self.app.logger.debug(f"Updating for {pull_request}")
        if pull_request.trello_cards:
            signed_off_count, required_signoffs_count = 0, 0
            for trello_card in pull_request.trello_cards:
                # TODO: Fix hydration here - O(n^2) API calls in worst case.
                trello_card.hydrate(trello_client=self.trello_client)
                if TrelloBoard.query.get(trello_card.board.id):
                    required_signoffs_count += 1

                    if TrelloList.query.get(trello_card.list.id):
                        signed_off_count += 1

            self.app.logger.debug(f"Required: {required_signoffs_count}, actual: {signed_off_count}")
            if signed_off_count < required_signoffs_count:
                self._set_pull_request_status(pull_request, StatusEnum.PENDING.value)
            else:
                self._set_pull_request_status(pull_request, StatusEnum.SUCCESS.value)

    def sync_pull_request(self, data):
        pull_request = PullRequest.from_json(data=data)
        trello_cards = get_trello_cards_from_text(trello_client=self.trello_client, text=pull_request.body)

        self._update_tracked_trello_cards(pull_request=pull_request, new_trello_cards=trello_cards)
        self._update_pull_request_status(pull_request)

        if self.user.checklist_feature_enabled:
            self._update_trello_checklists(pull_request)

    def sync_repositories(self, chosen_repo_ids):
        print(chosen_repo_ids)
        existing_repo_ids = {
            repo.id for repo in GithubRepo.query.filter(GithubRepo.integration == self.user.github_integration).all()
        }
        print(existing_repo_ids)

        repos_to_deintegrate = GithubRepo.query.filter(GithubRepo.id.in_(existing_repo_ids - chosen_repo_ids)).all()

        for repo in repos_to_deintegrate:
            try:
                self.github_client.delete_webhook(repo.id, repo.hook_id)
            except (GithubResourceMissing, GithubUnauthorized) as e:
                self.app.logger.warn(f"Unable to delete hook for {repo}: {e}")

            db.session.delete(repo)
            flash(f"This powerup is no longer monitoring the ‘{repo.fullname}’ repository.", "warning")

        for repo in chosen_repo_ids - existing_repo_ids:
            print("creating webhook for ", repo)
            hook_unique_slug = str(uuid.uuid4())
            hook_secret = token_urlsafe()
            hook = self.github_client.create_webhook(
                repo_id=repo,
                callback_url=url_for(
                    ".github_callback", _external=True, unique_slug=hook_unique_slug
                ),  # should be done by the client really
                secret=hook_secret,
                events=["pull_request"],
                active=True,
            )
            print(hook)
            repo = GithubRepo(
                id=repo,
                hook_id=hook["id"],
                hook_unique_slug=hook_unique_slug,
                hook_secret=hook_secret,
                integration=self.user.github_integration,
            )
            repo.hydrate(github_client=self.github_client)

            db.session.add(repo)
            flash(f"This powerup has been connected the ‘{repo.fullname}’ repository.", "info")

        db.session.commit()

    def transfer_repository(self, chosen_repo_id):
        print(f"{self.user} transferring repo {chosen_repo_id} to their account")
        github_repo = GithubRepo.query.get(chosen_repo_id)

        sparkpost.transmissions.send(
            recipients=[github_repo.integration.user.email],
            html=render_template(
                "email/repo-transferred.html",
                start_page_url=url_for(".start_page", _external=True),
                repo_fullname=github_repo.fullname,
                new_owner_email_address=self.user.email,
            ),
            from_email=self.app.config["MAIL_DEFAULT_SENDER"],
            subject=f"Repository transferred in {self.app.config['APP_NAME']}",
        )

        github_repo.integration = self.user.github_integration

        db.session.add(github_repo)
        db.session.commit()

        flash(
            f"You have transferred the connection to the ‘{github_repo.fullname}’ repository into your account.", "info"
        )

    def sync_trello_card(self, trello_card):
        self.app.logger.debug(f"Starting sync_trello_card for {trello_card}")

        if not trello_card.pull_requests:
            self.app.logger.debug("No pull requests - skipping")
            return

        for pull_request in trello_card.pull_requests:
            pull_request.hydrate(github_client=self.github_client)
            self._update_pull_request_status(pull_request)
