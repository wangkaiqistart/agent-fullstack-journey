"""校验计划的文件范围；只检查，不写入文件。"""

from pathlib import Path, PureWindowsPath

from schema import PatchPlan


def validate_workspace_path(file_path: str, workspace: Path) -> Path:
    # 统一要求 POSIX 相对路径，拒绝 Windows 盘符、反斜杠与绝对路径。
    if not file_path or "\\" in file_path or PureWindowsPath(file_path).drive:
        raise ValueError("必须提供工作区相对路径，使用 / 分隔")
    relative = Path(file_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("不允许绝对路径或 .. 路径段")

    root = workspace.resolve()
    if not root.is_dir():
        raise ValueError("工作区目录不存在")
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        # resolve() 会跟随已有符号链接，不能只判断字符串前缀。
        raise ValueError("路径越过工作区")
    if (not relative.parts or relative.parts[0] != "src"
            or not target.is_relative_to(root / "src") or target.suffix != ".py"):
        raise ValueError("本例仅允许 src/ 下的 Python 文件")
    if target.exists() and not target.is_file():
        raise ValueError("目标必须是文件")
    return target


def validate_plan_path(plan: PatchPlan, workspace: Path) -> Path | None:
    # 即使不是 edit，只要提供了路径也要检查范围。
    if plan.file_path is None:
        return None
    return validate_workspace_path(plan.file_path, workspace)


if __name__ == "__main__":
    workspace = Path(__file__).parent / "assets" / "workspace"
    for value in ["src/example.py", "../outside.py", "src/../../outside.py", ".env"]:
        try:
            validate_workspace_path(value, workspace)
            print(f"{value}: 通过")
        except ValueError as error:
            print(f"{value}: 拒绝，{error}")
