import logging

from flask import flash
from flask_login import current_user

from app import db
from app.constants import AWAITING_PRODUCT_REVIEW, TICKET_APPROVED_BY, APP_NAME, StatusEnum
from app.models import GithubRepo, TrelloCard, TrelloList, PullRequestStatus
from app.utils import get_github_client, get_trello_client, find_trello_card_ids_in_text


logger = logging.getLogger(__name__)


class Updater:
    def __init__(self, db, user):
        self.db = db
        self.user = user
        self.github_client = get_github_client(user)
        self.trello_client = get_trello_client(user)

    def _set_pull_request_status(self, pull_request, status):
        description = TICKET_APPROVED_BY if status == StatusEnum.SUCCESS.value else AWAITING_PRODUCT_REVIEW
        response = self.github_client.set_pull_request_status(
            repo_fullname=pull_request.repo.fullname,
            sha=pull_request.sha,
            status=status,
            description=description,
            context=APP_NAME,
        )

        if response.status_code != 201:
            logger.error(response, response.text)

    def _sync_trello_cards_for_pull_request(self, pull_request, body):
        all_trello_card_ids = find_trello_card_ids_in_text(body)
        existing_trello_card_ids = {
            card.card_id for card in TrelloCard.query.filter(TrelloCard.pull_request_id == pull_request.id).all()
        }

        # Old cards - need to remove
        for card_id in existing_trello_card_ids - all_trello_card_ids:
            old_trello_card = TrelloCard.query.filter(TrelloCard.card_id == card_id).one()
            db.session.delete(old_trello_card)

        # New cards - need to create
        for card_id in all_trello_card_ids - existing_trello_card_ids:
            new_trello_card = TrelloCard(card_id=card_id, pull_request_id=pull_request.id)
            db.session.add(new_trello_card)

    def sync_pull_request(self, id_, sha, body, github_repo):
        pull_request = PullRequestStatus.get_or_create(id_=id_, sha=sha, github_repo=github_repo, user=github_repo.user)

        self._sync_trello_cards_for_pull_request(pull_request=pull_request, body=body)

        db.session.add(pull_request)
        db.session.commit()

        signed_off_count = 0
        for trello_card in pull_request.trello_cards:
            trello_list = TrelloList.query.filter(
                TrelloList.list_id == self.trello_client.get_card_list(trello_card.card_id)["id"]
            ).first()

            if trello_list:
                signed_off_count += 1

        total_required_count = len(pull_request.trello_cards)
        if signed_off_count < total_required_count:
            self._set_pull_request_status(pull_request, StatusEnum.PENDING.value)
        else:
            self._set_pull_request_status(pull_request, StatusEnum.SUCCESS.value)

    def sync_repositories(self, chosen_repo_fullnames):
        existing_repo_fullnames = {
            repo.fullname for repo in GithubRepo.query.filter(GithubRepo.user_id == current_user.id).all()
        }

        repos_to_deintegrate = GithubRepo.query.filter(
            GithubRepo.fullname.in_(existing_repo_fullnames - chosen_repo_fullnames)
        ).all()

        for repo_to_deintegrate in repos_to_deintegrate:
            self.github_client.delete_webhook(repo_to_deintegrate.fullname, repo_to_deintegrate.hook_id)
            db.session.delete(repo_to_deintegrate)
            flash(f"Product signoff checks removed from the “{repo_to_deintegrate.fullname}” repository.")

        for repo_to_integrate in chosen_repo_fullnames - existing_repo_fullnames:
            hook = self.github_client.create_webhook(
                repo_fullname=repo_to_integrate,
                callback_url=url_for(".github_callback", _external=True),
                events=["pull_request"],
                active=True,
            )
            db.session.add(GithubRepo(fullname=repo_to_integrate, hook_id=hook["id"], user_id=current_user.id))
            flash(f"Product signoff checks added for the “{repo_to_integrate}” repository.")

        db.session.commit()

    def sync_trello_card(self, trello_cards):
        for trello_card in trello_cards:
            signed_off_count = 0

            for sub_trello_card in trello_card.pull_request.trello_cards:
                trello_list = TrelloList.query.filter(
                    TrelloList.list_id == self.trello_client.get_card_list(sub_trello_card.card_id)["id"]
                ).first()

                if trello_list:
                    signed_off_count += 1

            if signed_off_count < len(trello_card.pull_request.trello_cards):
                self._set_pull_request_status(pull_request=trello_card.pull_request, status=StatusEnum.PENDING.value)
            else:
                self._set_pull_request_status(pull_request=trello_card.pull_request, status=StatusEnum.SUCCESS.value)
