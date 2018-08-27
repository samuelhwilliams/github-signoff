import logging

from flask import flash, url_for
from flask_login import current_user

from app import db
from app.constants import AWAITING_PRODUCT_REVIEW, TICKET_APPROVED_BY, StatusEnum
from app.errors import TrelloInvalidRequest, TrelloResourceMissing
from app.models import GithubRepo, TrelloCard, TrelloList, TrelloChecklist, TrelloChecklistItem, PullRequestStatus
from app.utils import get_github_client, get_trello_client, find_trello_card_ids_in_text


logger = logging.getLogger(__name__)


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
            repo_id=pull_request.repo_id,
            sha=pull_request.sha,
            status=status,
            description=description,
            context=self.app.config["APP_NAME"],
        )

        if response.status_code != 201:
            logger.error(response, response.text)

    def _create_missing_trello_cards(self, pull_request, new_trello_card_ids):
        logger.debug(f"new cards: {new_trello_card_ids}")
        for card_id in new_trello_card_ids:
            try:
                trello_card = self.trello_client.get_card(card_id)
            except TrelloInvalidRequest:
                logger.warn(f"Ignoring invalid card {card_id}")
                continue

            trello_card.pull_requests = [pull_request]
            db.session.add(trello_card)

    def _delete_removed_trello_cards(self, pull_request, removed_trello_card_ids):
        logger.debug(f"old cards: {removed_trello_card_ids}")
        for card_id in removed_trello_card_ids:
            old_trello_card = TrelloCard.query.filter(TrelloCard.id == card_id).one()

            if old_trello_card.trello_checklist:
                trello_checklist_item = TrelloChecklistItem.query.filter(
                    TrelloChecklistItem.checklist == old_trello_card.trello_checklist,
                    TrelloChecklistItem.pull_request == pull_request,
                ).first()
                if trello_checklist_item:
                    self.trello_client.delete_checklist_item(
                        checklist_id=old_trello_card.trello_checklist.id, checklist_item_id=trello_checklist_item.id
                    )
            db.session.delete(old_trello_card)

    def _update_tracked_trello_cards(self, pull_request):
        all_trello_card_ids = find_trello_card_ids_in_text(pull_request.body)
        existing_trello_card_ids = {
            card.id for card in TrelloCard.query.filter(TrelloCard.pull_requests.contains(pull_request)).all()
        }
        logger.debug(existing_trello_card_ids)

        self._create_missing_trello_cards(pull_request, all_trello_card_ids - existing_trello_card_ids)
        self._delete_removed_trello_cards(pull_request, existing_trello_card_ids - all_trello_card_ids)

    def _update_trello_checklists(self, pull_request):
        trello_cards = TrelloCard.query.filter(TrelloCard.pull_requests.contains(pull_request)).all()
        print("update trello checklists: ", trello_cards)
        print([t.trello_checklist for t in trello_cards])

        for i, trello_card in enumerate(trello_cards):
            print(f"trello card #{i}: {trello_card}")
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

            found_trello_checklist_item = None
            for trello_checklist_item in trello_checklist.trello_checklist_items:
                if (
                    trello_checklist_item.checklist_id == trello_checklist.id
                    and trello_checklist_item.pull_request_id == pull_request.id
                ):
                    found_trello_checklist_item = trello_checklist_item
                    break

            trello_checklist_item = found_trello_checklist_item
            if trello_checklist_item:
                try:
                    trello_checklist_item.hydrate(trello_client=self.trello_client)

                except TrelloResourceMissing:
                    print("resource is missing, yep checkitem")
                    if trello_checklist_item:
                        print("deleting")
                        trello_checklist.trello_checklist_items.remove(trello_checklist_item)
                        db.session.add(trello_checklist)
                        db.session.delete(trello_checklist_item)
                        db.session.flush()
                        trello_checklist_item = None

            if not trello_checklist_item:
                trello_checklist_item = self.trello_client.create_checklist_item(
                    checklist_id=trello_checklist.id,
                    checklist_item_name=pull_request.url,
                    checked="true" if pull_request.pr_status == "closed" else "false",
                )
            elif (trello_checklist_item.state == "incomplete" and pull_request.pr_status == "closed") or (
                trello_checklist_item.state == "complete" and pull_request.pr_status == "open"
            ):
                self.trello_client.update_checklist_item(
                    real_card_id=trello_card.real_id,
                    checklist_item_id=trello_checklist_item.id,
                    state="complete" if pull_request.pr_status == "closed" else "incomplete",
                )

            trello_checklist.card_id = trello_card.id
            trello_checklist_item.pull_request_id = pull_request.id
            db.session.add(trello_checklist)
            db.session.add(trello_checklist_item)

        db.session.commit()

    def sync_pull_request(self, user, data):
        pull_request = PullRequestStatus.from_json(user=user, data=data)

        self._update_tracked_trello_cards(pull_request=pull_request)

        db.session.add(pull_request)
        db.session.commit()

        if user.checklist_feature_enabled:
            self._update_trello_checklists(pull_request)

        signed_off_count = 0
        for trello_card in pull_request.trello_cards:
            trello_list = TrelloList.query.filter(
                TrelloList.id == self.trello_client.get_card(trello_card.id).list.id
            ).first()

            if trello_list:
                signed_off_count += 1

        total_required_count = len(pull_request.trello_cards)
        if signed_off_count < total_required_count:
            self._set_pull_request_status(pull_request, StatusEnum.PENDING.value)
        else:
            self._set_pull_request_status(pull_request, StatusEnum.SUCCESS.value)

    def sync_repositories(self, chosen_repo_ids):
        print(chosen_repo_ids)
        existing_repo_ids = {
            repo.id
            for repo in GithubRepo.query.filter(
                GithubRepo.user_id == current_user.id
            ).all()
        }
        print(existing_repo_ids)

        repos_to_deintegrate = GithubRepo.query.filter(GithubRepo.id.in_(existing_repo_ids - chosen_repo_ids)).all()

        for repo in repos_to_deintegrate:
            self.github_client.delete_webhook(repo.id, repo.hook_id)
            db.session.delete(repo)
            flash(f"This powerup is no longer monitoring the ‘{repo.fullname}’ repository.", "warning")

        for repo in chosen_repo_ids - existing_repo_ids:
            print("creating webhook for ", repo)
            hook = self.github_client.create_webhook(
                repo_id=repo,
                callback_url=url_for(".github_callback", _external=True),
                events=["pull_request"],
                active=True,
            )
            print(hook)
            repo = GithubRepo(id=repo, hook_id=hook["id"], user_id=current_user.id)
            repo.hydrate(github_client=self.github_client)

            db.session.add(repo)
            flash(f"This powerup has been connected the ‘{repo.fullname}’ repository.", "info")

        db.session.commit()

    def sync_trello_card(self, trello_card):
        if not trello_card.pull_requests:
            return

        for pull_request in trello_card.pull_requests:
            signed_off_count = 0

            for sub_trello_card in pull_request.trello_cards:
                sub_trello_card.hydrate(trello_client=self.trello_client)
                trello_list = TrelloList.query.filter(TrelloList.id == sub_trello_card.list.id).first()

                if trello_list:
                    signed_off_count += 1

            if signed_off_count < len(pull_request.trello_cards):
                self._set_pull_request_status(pull_request=pull_request, status=StatusEnum.PENDING.value)
            else:
                self._set_pull_request_status(pull_request=pull_request, status=StatusEnum.SUCCESS.value)
