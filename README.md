# Powerup for Github and Trello

A powerup for integrating GitHub and Trello, with the following features:

* Add ‘sign-off’ checks to Pull Requests, indciating whether a ticket/story has been accepted by a product manager.
* Add links to pull requests on Trello cards.

## Dev machine dependencies

* Node 10.4.0
* Yarn (v1.9.4)

## TODO
* !!! trello+github callback URLs need to contain a secret for callback authentication !!!
* check that webhooks exist when going to /github/choose-repos
* Fix browser console errors
    * missing images/icon-pointer for start page
* multi user support
    * github/trello tokens with access to same repos/boards should be able to see/edit all their shared repos/board
* regular data deletions for old/unused accounts/hooks/tokens
* refactor api hydration calls to minimise external requests (check how many are being sent out and what's bad)
* work out why alembic is generating drop+create foreign key migrations
* logging to text or json streams - need to pass all variables in separate from formatted strings
* variable typing/annotations (mypy)
* change TrelloCard.id to real id of the card - add a hydrated 'short_link' (URL slug)



* Delete TrelloList entries when User.trello_token is invalid ???
* Infact - need to gracefully handle when the token expires