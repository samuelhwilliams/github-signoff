"""
TESTS TO WRITE:
* Logging out
* Generating a new login token invalidates the existing session
* tokens expire after 5 minutes
* session expires after 60 minutes
* incoming callbacks make correct DB checks and call outs
* test trello/github clients NEVER log tokens (use https://testfixtures.readthedocs.io/en/latest/logging.html)
* account deletion removes all db records
* all forms securely validate their input and protect against forged POSTs (i.e. user 1 can't edit/delete user 2's 
    resources)
"""
