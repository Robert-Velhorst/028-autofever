import ast
import unittest
from pathlib import Path


class LegacyErrorResponseTests(unittest.TestCase):
    @staticmethod
    def _returned_exception_references(handler):
        if not handler.name:
            return []
        return [
            returned
            for returned in (node for node in ast.walk(handler) if isinstance(node, ast.Return) and node.value)
            if any(
                isinstance(node, ast.Name) and node.id == handler.name
                for node in ast.walk(returned.value)
            )
        ]

    def test_detector_catches_common_exception_wrappers(self):
        for expression in (
            "e",
            "str(e)",
            "repr(e)",
            "f'failure: {e}'",
            "e.args",
        ):
            with self.subTest(expression=expression):
                tree = ast.parse(f"def handler():\n    try:\n        pass\n    except Exception as e:\n        return {expression}\n")
                handler = next(node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler))
                self.assertTrue(self._returned_exception_references(handler))

    def test_exception_objects_are_not_returned_to_legacy_callers(self):
        source = Path(__file__).resolve().parents[2] / 'app_enhanced_optimized_fixed.py'
        if not source.is_file():
            self.skipTest('retired prototype is intentionally omitted from the isolated backend test image')
        tree = ast.parse(source.read_text(encoding='utf-8'))
        for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler) and node.name):
            for returned in self._returned_exception_references(handler):
                self.fail(f'Exception value returned at line {returned.lineno}')


if __name__ == '__main__':
    unittest.main()
