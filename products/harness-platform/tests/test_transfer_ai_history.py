"""History projection distinguishes file-only user turns from server exchanges.

The attachment history is a controlled boundary fixture; file parsing itself is
covered by the native media/browser suites. No provider or external IO is used.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from platform_core.guest_registration import RegistrationStore
from platform_core import account_lifecycle, podmasterye_domain as domain
from platform_core import podmasterye_timer as timer, podmasterye_workshops as workshops
from platform_core.podmasterye_chat_context import ChatContext


class HistoryProjection(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.identity = self.enterContext(RegistrationStore(self.root / 'history.sqlite3'))
        domain.init(self.identity)
        with self.identity._write() as db:
            account_lifecycle.initialize(db)
            timer.initialize(db)
        self.identity.create_account('history-owner', 'temporary history password')
        self.token = self.identity.login('history-owner', 'temporary history password')
        chat = workshops.choose_chat(self.identity, self.token)['chatId']
        self.scope = self.identity.resolve_chat(self.token, chat)

    def file_turn(self):
        # A request ID prefix is not authority to suppress a user's message.
        rid = 'timer_user_selected_filename'
        file_id = 'f' * 32
        selected, cached = domain.decide(self.identity, self.scope, self.token,
            rid, '', attachment_ids=[file_id])
        self.assertEqual((selected, cached), ('model', None))
        answer = domain.complete(self.identity, self.scope, self.token, rid,
            {'role': 'assistant', 'requestId': rid, 'text': 'Маркер отчёта: 714598.'})
        return rid, file_id, answer

    async def test_file_only_user_survives_history_and_attachment_enrichment(self):
        rid, file_id, answer = self.file_turn()
        attachment = {'attachmentId': file_id, 'name': 'отчёт.xlsx',
            'download': '/api/chats/' + self.scope.chat_id + '/files/' + file_id}
        native = [{'role': 'user', 'requestId': rid, 'text': '', 'attachments': [attachment]}, answer]
        worker = SimpleNamespace(request=AsyncMock(return_value=native))
        context = ChatContext(SimpleNamespace(identity=self.identity, worker=worker))
        messages = domain.history(self.identity, self.token, self.scope, 50)
        self.assertEqual([(m['role'], m['text']) for m in messages],
            [('user', ''), ('assistant', 'Маркер отчёта: 714598.')])
        with patch.object(context, 'has_files', return_value=True):
            await context.enrich(self.scope, messages)
        worker.request.assert_awaited_once_with(self.scope, 'history', limit=50)
        self.assertEqual(messages[0]['attachments'], [attachment])
        self.assertNotIn('attachments', messages[1])
        # A reload/retry preserves the same single pair, without another turn.
        self.assertEqual(domain.decide(self.identity, self.scope, self.token,
            rid, '', attachment_ids=[file_id]), ('model', answer))
        with RegistrationStore(self.root / 'history.sqlite3') as reopened:
            self.assertEqual(domain.history(reopened, self.token, self.scope, 50),
                [{k: v for k, v in m.items() if k != 'attachments'} for m in messages])

    async def test_real_timer_publication_adds_only_assistant_to_mixed_history(self):
        rid, _, _ = self.file_turn()
        definition = {'title': 'История таймера', 'kind': 'report',
            'schedule': {'kind': 'interval', 'zone': 'UTC', 'every_us': 60_000_000},
            'channels': ['chat'], 'report': {'report': 'profit', 'period': 'today'}}
        with self.identity._write() as db:
            preview = timer.prepare(db, self.scope, 'preview', definition)
            event = timer.confirm(db, self.scope, 'confirm', preview['id'],
                preview['revision'], preview['receipt'])
            run = timer.control(db, self.scope, 'run', event['id'], 'run', event['revision'])['runId']
        answer = 'Отчёт по расписанию: выручка 0 ₽.'
        worker = SimpleNamespace(request=AsyncMock(return_value={'role': 'assistant', 'text': answer}))
        runtime = timer.Runtime(SimpleNamespace(identity=self.identity, worker=worker))
        await runtime.publish(self.scope, run, answer)
        await runtime.publish(self.scope, run, answer)
        messages = domain.history(self.identity, self.token, self.scope, 50)
        self.assertEqual([(m['role'], m['requestId']) for m in messages],
            [('user', rid), ('assistant', rid), ('assistant', 'timer_' + run)])
        self.assertIs(messages[-1]['system'], True)
        self.assertEqual(messages[-1]['text'], answer)
        self.assertEqual(domain.history(self.identity, self.token, self.scope, 1), [messages[-1]])
        self.assertEqual(self.identity._db.execute('SELECT COUNT(*) FROM coin_attempts').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
