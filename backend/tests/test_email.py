"""Email notifications: the words, the queueing rules, retry timing and the sender. No database, no network."""

from contextlib import contextmanager
from types import SimpleNamespace

from app.email import outbox, ses, templates


def settings(**kw):
    base = dict(email_enabled=True, email_from="PerkFlex <no-reply@example.com>", email_configuration_set="", aws_region="us-east-1")
    return SimpleNamespace(**{**base, **kw})


def test_every_kind_has_a_subject_and_the_body_carries_the_notice_and_the_concept_footer():
    for kind in ("BOOKED", "RELEASE", "PURCHASE", "COMPLETE"):
        assert templates.subject_for(kind).startswith("PerkFlex")
        text = templates.body_text(kind, "All set! 800 points are pending.")
        assert "800 points are pending" in text and "not affiliated with Southwest" in text and "turn off Email notifications" in text


def test_the_confirmation_email_has_the_link_and_says_what_to_do_if_unexpected():
    text = templates.body_text("CONFIRM", link="https://x.test/api/email/confirm?token=abc")
    assert "https://x.test/api/email/confirm?token=abc" in text and "did not ask for this" in text


def test_html_escapes_the_text():
    assert "&lt;script&gt;" in templates.body_html("<script>alert(1)</script>") and "<script>" not in templates.body_html("<script>")


def test_which_actions_send_mail():
    assert outbox.EMAIL_KIND_BY_ACTION == {"book": "BOOKED", "release": "RELEASE", "redeem": "PURCHASE", "complete": "COMPLETE"}


def test_backoff_grows_and_stops_growing():
    assert [ses.backoff(n) for n in (1, 2, 3, 4, 9)] == [60, 300, 900, 3600, 3600]


class Result:
    def __init__(self, row): self.row = row
    def fetchone(self): return self.row


class FakeConn:
    """Records SQL. `account` is what the account lookup returns; `insert` what the outbox insert returns."""
    def __init__(self, account=None, insert=(1,)):
        self.account, self.insert, self.sql = account, insert, []
    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        if "FROM dim_user_account" in sql: return Result(self.account)
        if "INSERT INTO fact_email_outbox" in sql: return Result({"email_id": 1} if self.insert else None)
        return Result(None)
    class info: transaction_status = 1
    @contextmanager
    def transaction(self): yield


def inserts(conn): return [p for s, p in conn.sql if "INSERT INTO fact_email_outbox" in s]


def test_mail_is_queued_only_for_a_confirmed_address_with_notifications_on():
    conn = FakeConn(account={"email": "maya@example.com"})
    assert outbox.queue_for_traveller(conn, "P01", "RELEASE", "All set!", "P01:k1:RELEASE")
    (row,) = inserts(conn)
    assert row[0] == "P01" and row[1] == "RELEASE" and row[2] == "maya@example.com" and row[5] == "P01:k1:RELEASE"
    # the lookup itself only matches confirmed, opted-in accounts
    lookup = next(s for s, _ in conn.sql if "FROM dim_user_account" in s)
    assert "email_verified_flag" in lookup and "email_opt_in_flag" in lookup
    none = FakeConn(account=None)
    assert not outbox.queue_for_traveller(none, "P01", "RELEASE", "All set!", None) and inserts(none) == []


def test_a_duplicate_key_queues_nothing_new():
    conn = FakeConn(account={"email": "m@example.com"}, insert=None)
    assert outbox.queue_for_traveller(conn, "P01", "RELEASE", "x", "same-key") is False


def test_a_queueing_failure_never_raises():
    class Boom(FakeConn):
        def execute(self, sql, params=()):
            if "INSERT" in sql: raise RuntimeError("database trouble")
            return super().execute(sql, params)
    assert outbox.queue(Boom(), "P01", "RELEASE", "m@example.com", notice="x") is False


def test_deliver_reports_each_result_and_one_failure_does_not_stop_the_rest():
    rows = [{"email_id": 1}, {"email_id": 2}, {"email_id": 3}]
    def send(row):
        if row["email_id"] == 2: raise RuntimeError("MessageRejected")
    assert ses.deliver(rows, send) == [(1, None), (2, "MessageRejected"), (3, None)]


def test_the_ses_call_has_sender_recipient_text_and_html():
    calls = []
    client = SimpleNamespace(send_email=lambda **kw: calls.append(kw))
    ses.send_one(client, settings(email_configuration_set="perkflex"), {"to_address": "m@example.com", "subject": "S", "body_text": "Hello\n\nthere"})
    (c,) = calls
    assert c["FromEmailAddress"].endswith("<no-reply@example.com>") and c["Destination"] == {"ToAddresses": ["m@example.com"]}
    body = c["Content"]["Simple"]["Body"]
    assert body["Text"]["Data"] == "Hello\n\nthere" and "<p>Hello</p>" in body["Html"]["Data"] and c["ConfigurationSetName"] == "perkflex"


def test_nothing_is_sent_or_read_when_email_is_off():
    assert ses.run_once(settings(email_enabled=False)) == 0
    assert ses.run_once(settings(email_from="")) == 0
