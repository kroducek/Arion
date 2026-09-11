"""Ověří, že každý modul v src/ jde naimportovat a že cogy v BOT_COGS/DND_COGS existují."""
import importlib
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _iter_modules():
    for path in sorted((ROOT / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield ".".join(path.relative_to(ROOT).with_suffix("").parts)


def _cog_list(entrypoint: str):
    text = (ROOT / entrypoint).read_text(encoding="utf-8")
    body = re.search(r"COGS = \[(.*?)\]", text, re.S).group(1)
    return re.findall(r'"(src\.[\w.]+)"', body)


class TestImports(unittest.TestCase):
    def test_all_modules_importable(self):
        for module in _iter_modules():
            with self.subTest(module=module):
                importlib.import_module(module)

    def test_listed_cogs_exist(self):
        for entrypoint in ("main_bot.py", "main_dnd.py"):
            for cog in _cog_list(entrypoint):
                with self.subTest(entrypoint=entrypoint, cog=cog):
                    self.assertTrue(
                        (ROOT / pathlib.Path(*cog.split("."))).with_suffix(".py").exists(),
                        f"{cog} je v {entrypoint}, ale soubor neexistuje",
                    )

    def test_listed_cogs_have_setup(self):
        for entrypoint in ("main_bot.py", "main_dnd.py"):
            for cog in _cog_list(entrypoint):
                with self.subTest(entrypoint=entrypoint, cog=cog):
                    self.assertTrue(
                        hasattr(importlib.import_module(cog), "setup"),
                        f"{cog} nemá async setup(bot)",
                    )


if __name__ == "__main__":
    unittest.main()
