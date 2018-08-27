"""initial setup - revisited

Revision ID: 1
Revises: 
Create Date: 2018-08-27 11:26:11.475071

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("trello_card", sa.Column("id", sa.Text(), nullable=False), sa.PrimaryKeyConstraint("id"))
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("checklist_feature_enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_email"), "user", ["email"], unique=False)
    op.create_table(
        "github_integration",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("oauth_state", sa.Text(), nullable=False),
        sa.Column("oauth_token", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "login_token",
        sa.Column("guid", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("guid"),
    )
    op.create_index(op.f("ix_login_token_user_id"), "login_token", ["user_id"], unique=False)
    op.create_table(
        "trello_checklist",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("card_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("card_id"),
    )
    op.create_table(
        "trello_integration",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("oauth_token", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "github_repo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fullname", sa.Text(), nullable=False),
        sa.Column("hook_id", sa.Text(), nullable=True),
        sa.Column("hook_unique_slug", sa.Text(), nullable=True),
        sa.Column("hook_secret", sa.Text(), nullable=True),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fullname"),
        sa.UniqueConstraint("hook_unique_slug"),
    )
    op.create_index(op.f("ix_github_repo_hook_secret"), "github_repo", ["hook_secret"], unique=False)
    op.create_index(op.f("ix_github_repo_fullname"), "github_repo", ["fullname"], unique=False)
    op.create_table(
        "trello_list",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("hook_id", sa.Text(), nullable=True),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "pull_request",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "pull_request_trello_card",
        sa.Column("card_id", sa.Text(), nullable=False),
        sa.Column("pull_request_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("card_id", "pull_request_id"),
    )
    op.create_table(
        "trello_checkitem",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("checklist_id", sa.Text(), nullable=False),
        sa.Column("pull_request_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checklist_id", "pull_request_id", name="uix_checklist_id_pull_request_id"),
    )

    op.create_foreign_key(
        "fk_github_integration_user_id", "github_integration", "user", ["user_id"], ["id"], ondelete="cascade"
    )
    op.create_foreign_key("fk_login_token_user_id", "login_token", "user", ["user_id"], ["id"], ondelete="cascade")
    op.create_foreign_key(
        "fk_trello_checklist_trello_card_id", "trello_checklist", "trello_card", ["card_id"], ["id"], ondelete="cascade"
    )
    op.create_foreign_key(
        "fk_trello_integration_user_id", "trello_integration", "user", ["user_id"], ["id"], ondelete="cascade"
    )
    op.create_foreign_key(
        "fk_github_repo_github_integration_user_id",
        "github_repo",
        "github_integration",
        ["integration_id"],
        ["user_id"],
        ondelete="cascade",
    )
    op.create_foreign_key(
        "fk_trello_list_trello_integration_user_id",
        "trello_list",
        "trello_integration",
        ["integration_id"],
        ["user_id"],
        ondelete="cascade",
    )
    op.create_foreign_key(
        "fk_pull_request_github_repo_id", "pull_request", "github_repo", ["repo_id"], ["id"], ondelete="cascade"
    )
    op.create_foreign_key("fk_pull_request_user_id", "pull_request", "user", ["user_id"], ["id"], ondelete="cascade")
    op.create_foreign_key(
        "fk_pull_request_trello_card_card_id",
        "pull_request_trello_card",
        "trello_card",
        ["card_id"],
        ["id"],
        ondelete="cascade",
    )
    op.create_foreign_key(
        "fk_pull_request_trello_card_pull_request_id",
        "pull_request_trello_card",
        "pull_request",
        ["pull_request_id"],
        ["id"],
        ondelete="cascade",
    )
    op.create_foreign_key(
        "fk_trello_checkitem_trello_checklist_id",
        "trello_checkitem",
        "trello_checklist",
        ["checklist_id"],
        ["id"],
        ondelete="cascade",
    )
    op.create_foreign_key(
        "fk_trello_checkitem_pull_request_id",
        "trello_checkitem",
        "pull_request",
        ["pull_request_id"],
        ["id"],
        ondelete="cascade",
    )


def downgrade():
    op.drop_table("trello_checkitem")
    op.drop_table("pull_request_trello_card")
    op.drop_table("pull_request")
    op.drop_table("trello_list")
    op.drop_index(op.f("ix_github_repo_fullname"), table_name="github_repo")
    op.drop_index(op.f("ix_github_repo_hook_secret"), table_name="github_repo")
    op.drop_table("github_repo")
    op.drop_table("trello_integration")
    op.drop_table("trello_checklist")
    op.drop_index(op.f("ix_login_token_user_id"), table_name="login_token")
    op.drop_table("login_token")
    op.drop_table("github_integration")
    op.drop_index(op.f("ix_user_email"), table_name="user")
    op.drop_table("user")
    op.drop_table("trello_card")
