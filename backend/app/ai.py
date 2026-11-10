class MockProvider:
    mode = "MOCK"

    def status(self):
        return {"mode": self.mode, "available": True, "reason": "mock_adapter_only"}

    def chat(self, _text: str):
        return {"mode": self.mode, "text": "M1 Mock adapter; no business analysis implemented."}

    def structured_generate(self, text: str):
        # Deterministic demonstration grammar, not a real model or factual verifier.
        from app.meetings.schemas import TOPICS, Extraction

        labels = {
            "需求": "needs",
            "预算": "budget",
            "联系人": "contacts",
            "决策人": "decision_maker",
            "成交时间": "close_date",
            "预计成交日期": "close_date",
            "待办": "tasks",
            "任务": "tasks",
            "主要联系人ID": "contacts",
            "风险": "risks",
        }
        found, offset = {}, 0
        for line in text.splitlines(keepends=True):
            for label, topic in labels.items():
                for separator in ("：", ":"):
                    prefix = label + separator
                    if line.startswith(prefix) and topic not in found:
                        value = line[len(prefix) :].strip()
                        if value and len(value) <= 2000:
                            start = offset + line.index(value, len(prefix))
                            found[topic] = {
                                "topic": topic,
                                "kind": "FACT",
                                "value": value,
                                "evidence": [
                                    {"start": start, "end": start + len(value), "quote": value}
                                ],
                            }
            offset += len(line)
        return (
            Extraction(
                mode="MOCK",
                schema_version="meeting-v1",
                facts=[
                    found.get(
                        topic, {"topic": topic, "kind": "UNKNOWN", "value": None, "evidence": []}
                    )
                    for topic in TOPICS
                ],
            )
            .verify_source(text)
            .model_dump(mode="json")
        )

    def embed(self, _texts: list[str]):
        raise NotImplementedError("Embedding starts at M4")
