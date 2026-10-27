class MockProvider:
    mode = "MOCK"

    def status(self):
        return {"mode": self.mode, "available": True, "reason": "mock_adapter_only"}

    def chat(self, _text: str):
        return {"mode": self.mode, "text": "M1 Mock adapter; no business analysis implemented."}

    def structured_generate(self, _text: str):
        raise NotImplementedError("Meeting extraction starts at M3")

    def embed(self, _texts: list[str]):
        raise NotImplementedError("Embedding starts at M4")
