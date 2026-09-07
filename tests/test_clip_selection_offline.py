"""Offline regression tests. Network and paid clients are blocked by default."""
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import fetch_stock_video as stock

CANDIDATES = [dict(id=i, link=f'https://invalid/clip{i}', preview=f'https://invalid/poster{i}') for i in range(1, 5)]


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, kwargs in [
            ('fetch_stock_video._VISION_CACHE_FILE', {'new': str(Path(self.tmp.name) / 'cache.json')}),
            ('fetch_stock_video._stats', {'new': dict(stock._STATS_TEMPLATE)}),
            ('requests.sessions.Session.request', {'side_effect': AssertionError('Network forbidden')}),
            ('socket.create_connection', {'side_effect': AssertionError('Network forbidden')}),
        ]:
            p = patch(target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        self.client_patch = patch.object(stock, 'Anthropic', side_effect=AssertionError('Paid API forbidden'))
        self.client = self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        env = patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'offline-dummy'})
        env.start()
        self.addCleanup(env.stop)

    def response(self, raw, stop='end_turn'):
        self.client.side_effect = None
        self.client.return_value = NS(messages=NS(create=Mock(return_value=NS(
            content=[NS(type='text', text=raw)], stop_reason=stop,
            usage=NS(input_tokens=123, output_tokens=12)))))
        return self.client.return_value.messages.create

    def test_wrapped_json_is_accepted(self):
        """Реальные ответы из прод-лога (2026-09-07, ролик 2gD7Jh7lUa8): модель кладёт JSON
        в markdown-заборчик и дописывает объяснение. Это ОДОБРЕНИЕ, а не брак."""
        fence = '```json\n'
        self.assertEqual(stock._parse_selection(
            fence + '{"approved":[1]}\n```\n\nClip 1 is the only appropriate choice.', 4), [1])
        self.assertEqual(stock._parse_selection(
            fence + '{"approved":[2,1]}\n```\n\n**Reasoning:**\n\nClip 2 is best', 4), [2, 1])
        self.assertEqual(stock._parse_selection('{"approved":[1]} explanation', 4), [1])
        self.assertEqual(stock._parse_selection(fence + '{"approved":[]}\n```\nNone fit.', 4), [])

    def test_strict_contract(self):
        self.assertEqual(stock._parse_selection('{"approved":[3,1]}', 4), [3, 1])
        self.assertEqual(stock._parse_selection('{"approved":[]}', 4), [])
        # 2026-09-07: обёртка вокруг JSON больше НЕ брак. Модель в проде стабильно отвечает
        # ```json-заборчиком с рассуждением после, и требование «строго JSON» съело 4 бита
        # из 5 в ролике 2gD7Jh7lUa8 — кадры были одобрены, но не попали в него. Содержимое
        # объекта валидируется так же строго, см. кейсы ниже и test_wrapped_json_is_accepted.
        for raw in ['3,1', 'Clip 3', '0 None of these clips show a pyramid.',
                    'None of these clips show a pyramid.', '{"approved":[true]}',
                    '{"approved":[0,1]}', '{"approved":[1,10]}', '{"approved":[1,1]}',
                    '{"approved":["1"]}', '{"approved":[1],"extra":3}',
                    '{"approved":null}', '[]',
                    '```json\n{"approved":[1', '{"approved":[1']:  # обрезан по max_tokens
            with self.subTest(raw=raw):
                self.assertIsNone(stock._parse_selection(raw, 4))

    def test_only_approved_backups_and_usage(self):
        create = self.response('{"approved":[3,1]}')
        clips, outcome = stock._accepted_clips(CANDIDATES, 'african wildlife', 'A bird hunts snakes.')
        self.assertEqual([c['id'] for c in clips], [3, 1])
        self.assertEqual(outcome, 'vetted')
        self.client.assert_called_once_with(api_key='offline-dummy', max_retries=0)
        self.assertIn('A bird hunts snakes.', create.call_args.kwargs['messages'][0]['content'][0]['text'])
        self.assertEqual(stock.selection_stats()['input_tokens'], 123)
        self.assertEqual(stock.selection_stats()['output_tokens'], 12)

    def test_unknown_and_truncated_fail_closed(self):
        for raw, stop, outcome in [('None fit', 'end_turn', 'unparsed'),
                                    ('{"approved":[1]}', 'max_tokens', 'unparsed'),
                                    ('{"approved":[]}', 'end_turn', 'rejected')]:
            self.response(raw, stop)
            self.assertEqual(stock._accepted_clips(CANDIDATES, 'query'), ([], outcome))

    def test_no_preview_and_api_error_fail_closed(self):
        self.assertEqual(stock._accepted_clips([dict(id=1)], 'query'), ([], 'no_preview'))
        self.client.assert_not_called()
        self.client.side_effect = RuntimeError('service unavailable')
        self.assertEqual(stock._accepted_clips(CANDIDATES, 'query'), ([], 'api_error'))

    def test_single_preview_is_checked(self):
        create = self.response('{"approved":[]}')
        self.assertEqual(stock._accepted_clips(CANDIDATES[:1], 'query'), ([], 'rejected'))
        create.assert_called_once()

    def test_cache_separates_narration_and_versions(self):
        create = self.response('{"approved":[1]}')
        stock._accepted_clips(CANDIDATES, 'wildlife', 'bird')
        self.assertEqual(stock._accepted_clips(CANDIDATES, 'wildlife', 'bird')[1], 'cache_hit')
        stock._accepted_clips(CANDIDATES, 'wildlife', 'giraffe')
        self.assertEqual(create.call_count, 2)
        cache = json.loads(Path(stock._VISION_CACHE_FILE).read_text())
        for entry in cache.values():
            entry['v'] = stock._VISION_CACHE_VERSION - 1
        Path(stock._VISION_CACHE_FILE).write_text(json.dumps(cache))
        stock._accepted_clips(CANDIDATES, 'wildlife', 'bird')
        self.assertEqual(create.call_count, 3)

    def test_rejection_has_no_paid_retry_or_bypass(self):
        create = self.response('{"approved":[]}')
        with patch.object(stock, '_get_candidates', return_value=CANDIDATES) as search:
            self.assertEqual(stock.fetch_clips(['african bird hunting'], self.tmp.name, narration='bird'), [])
        search.assert_called_once()
        create.assert_called_once()
        self.assertFalse(stock.selection_stats()['bypass'])
        self.assertEqual(stock.selection_stats()['rejected'], 1)

    def test_empty_search_simplifies_without_losing_context(self):
        create = self.response('{"approved":[1]}')
        with patch.object(stock, '_get_candidates', side_effect=[[], CANDIDATES]) as search:
            stock._search_with_fallback('african bird hunting', set(), 'The bird hunts snakes.')
        self.assertEqual(search.call_count, 2)
        create.assert_called_once()
        prompt = create.call_args.kwargs['messages'][0]['content'][0]['text']
        self.assertIn('african bird hunting', prompt)
        self.assertIn('The bird hunts snakes.', prompt)

    def test_missing_results_and_search_errors_are_counted(self):
        with patch.object(stock, '_get_candidates', return_value=[]):
            stock._search_with_fallback('bird', set())
        with patch.object(stock, '_get_candidates', side_effect=RuntimeError('stock down')):
            with self.assertRaises(RuntimeError):
                stock._search_with_fallback('bird', set())
        self.assertEqual(stock.selection_stats()['beats'], 2)
        self.assertEqual(stock.selection_stats()['no_candidates'], 1)
        self.assertEqual(stock.selection_stats()['search_error'], 1)

    def test_broken_winner_uses_only_approved_backup(self):
        self.response('{"approved":[3,1]}')
        downloaded = []
        def download(url, **kwargs):
            downloaded.append(url)
            return NS(content=b'fake-video', raise_for_status=lambda: None)
        with patch.object(stock, '_get_candidates', return_value=CANDIDATES), \
             patch.object(stock.requests, 'get', side_effect=download), \
             patch.object(stock, '_is_valid_clip', side_effect=[False, True]):
            paths = stock.fetch_clips(['bird'], self.tmp.name, narration='The bird hunts snakes.')
        self.assertEqual(len(paths), 1)
        self.assertEqual(downloaded, ['https://invalid/clip3', 'https://invalid/clip1'])

    def test_saved_queue_context_without_network(self):
        queue = json.loads((ROOT / 'queue_es.json').read_text(encoding='utf-8'))
        self.assertTrue(queue)
        with patch.object(stock, '_search_with_fallback', return_value=[]) as search:
            for data in queue[:3]:
                stock.fetch_clips(data['video_queries'], self.tmp.name, narration=data['script'])
                contexts = [c.args[2] for c in search.call_args_list[-len(data['video_queries']):]]
                self.assertTrue(all(data['script'] in context for context in contexts))
                self.assertTrue(contexts[0].startswith('Shot 1 of '))
        self.client.assert_not_called()

    def test_pipeline_stops_before_tts_when_no_clips(self):
        tree = ast.parse((ROOT / 'src/pipeline.py').read_text(encoding='utf-8'))
        run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run')
        guard = next(node for node in ast.walk(run) if isinstance(node, ast.If)
                     and ast.unparse(node.test) == 'not clip_paths')
        with self.assertRaisesRegex(RuntimeError, 'Нет проверенных'):
            exec(compile(ast.Module(body=[guard], type_ignores=[]), '<guard>', 'exec'), {'clip_paths': []})
        tts = next(node for node in ast.walk(run) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name) and node.func.id == 'text_to_speech')
        self.assertLess(guard.lineno, tts.lineno)


if __name__ == '__main__':
    unittest.main()
