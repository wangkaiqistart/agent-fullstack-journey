"""离线演示：格式错误经过一次纠错后通过；连续失败则停止。"""

from decision import AgentDecision
from fallback import choose_result, demo_cache
from repair_loop import repair_until_valid


def main():
    valid = '{"action":"search_docs","query":"差旅报销材料","answer":null}'
    attempts = iter([valid])
    result, repairs = repair_until_valid('{"action":"search_docs","answer":null}', lambda _feedback: next(attempts))
    print(f"一次修复：status={'OK' if result.ok else 'FAILED'}，repair_count={repairs}")

    failed, repairs = repair_until_valid("{bad", lambda _feedback: "{bad", max_repairs=2)
    fallback = choose_result(
        failed.decision,
        task_key="expense-materials",
        protocol_version="1",
        cache=demo_cache(AgentDecision(action="finish", query=None, answer="请查阅最新制度。")),
    )
    print(f"连续失败：status={fallback.status}，repair_count={repairs}，reason={fallback.reason}")


if __name__ == "__main__":
    main()
