"""Hlídá limit Discordu (100 top-level příkazů na aplikaci) a překryv jmen mezi boty.

Počítá staticky z kódu — skupina (`app_commands.Group`) se počítá jako jeden
příkaz, její podpříkazy ne.
"""
import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIMIT = 100
ENTRYPOINTS = ("main_bot.py", "main_dnd.py", "main_dm.py")


def _cog_list(entrypoint: str) -> list[str]:
    text = (ROOT / entrypoint).read_text(encoding="utf-8")
    body = re.search(r"COGS = \[(.*?)\]", text, re.S).group(1)
    return re.findall(r'"(src\.[\w.]+)"', body)


def _const_name(call: ast.Call) -> str | None:
    for kw in call.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return None


def _top_level_names(module: str) -> set[str]:
    path = ROOT / pathlib.Path(*module.split("."))
    tree = ast.parse(path.with_suffix(".py").read_text(encoding="utf-8"))
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and func.attr == "Group":
                name = _const_name(node.value)
                if name:
                    names.add(name)

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
                    continue
                if deco.func.attr != "command":
                    continue
                base = deco.func.value
                is_top = (isinstance(base, ast.Name) and base.id == "app_commands") or (
                    isinstance(base, ast.Attribute) and base.attr == "app_commands"
                )
                name = _const_name(deco)
                if is_top and name:
                    names.add(name)

    return names


def _bot_commands(entrypoint: str) -> set[str]:
    names: set[str] = set()
    for cog in _cog_list(entrypoint):
        names |= _top_level_names(cog)
    return names


class CommandLimitTests(unittest.TestCase):
    def test_under_discord_limit(self):
        for entrypoint in ENTRYPOINTS:
            with self.subTest(entrypoint=entrypoint):
                names = _bot_commands(entrypoint)
                self.assertLess(
                    len(names), LIMIT,
                    f"{entrypoint} má {len(names)} top-level příkazů — limit Discordu je {LIMIT}",
                )

    def test_dm_commands_are_unique(self):
        dm = _bot_commands("main_dm.py")
        for entrypoint in ("main_bot.py", "main_dnd.py"):
            with self.subTest(entrypoint=entrypoint):
                clash = dm & _bot_commands(entrypoint)
                self.assertEqual(
                    set(), clash,
                    f"ArionDM a {entrypoint} registrují stejné příkazy: {sorted(clash)}",
                )


if __name__ == "__main__":
    unittest.main()
