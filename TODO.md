* !!! trello+github callback URLs need to contain a secret for callback authentication !!!
* PR checklists on trello cards (see below)
* check that webhooks exist when going to /github/choose-repos
* Fix console errors
    * missing images/icon-pointer for start page
* multi user support
    * github/trello tokens with access to same repos/boards should be able to see/edit all their shared repos/board
* daily data deletions for old/unused accounts/hooks/tokens
* refactor api hydration calls to minimise external requests (check how many are being sent out and what's bad)
* work out why alembic is generating drop+create foreign key migrations
* logging to text or json streams - need to pass all variables in separate from formatted strings
* variable typing/annotations
* change TrelloCard.id to real id of the card - add a hydrated 'short_link' (URL slug)




TODO:
* Delete TrelloList entries when User.trello_token is invalid ???
* Infact - need to gracefully handle when the token expires



PR checklists on trello cards:
* 1) Check if Pull Request exists in the database
* 2) Check if Pull Request contains links to any trello card(s)
* 3) 
    * a) if not to both: exit
    * b) if yes to 1 only: goto x
    * c) if yes to 2 only: goto 5
    * d) if yes to both: goto 6
* 4)
    * Remove PR from checklists of any associated trello cards.
    * Delete from database
    * exit
* 5)
    * Create a new PullRequest record in the database.
* 6)
    * Add a 'Pull Request' checklist item for each card (if doesn't already exist).
    * Check existing 
    * Record a reference to the checklist item (separate table)
    * For any referenced trello cards where the PR is not already on its checklist, add it.
    * Record a reference to any new checklist item
    * Check whether the referenced trello card(s) are in a 'product signoff' list:
        * If yes for all: create a status on the PR indicating the ticket has been signed off.
        * If no for any: create a status on the PR indicating the ticket is pending product review
            * Include the number that are signed off vs the number that need signed off.

On Trello callback:
* Check that the action is 'updateCard':
    * If no: ignore.
    * If yes:
        * Check whether the trello card contains links to any pull requests.
