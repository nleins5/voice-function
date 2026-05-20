class DummySeg:
    def __init__(self):
        self.start = 1.0
        self.end = 2.0
seg = DummySeg()
print(isinstance(seg, dict))
print(getattr(seg, "start", 0))
