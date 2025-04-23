# dummy_gpio.py

class DummyGPIO:
    BCM = "BCM"
    OUT = "OUT"
    IN = "IN"
    HIGH = 1
    LOW = 0

    def setmode(self, mode):
        print(f"[Dummy GPIO] setmode({mode})")

    def setup(self, pin, mode):
        print(f"[Dummy GPIO] setup(pin={pin}, mode={mode})")

    def output(self, pin, state):
        print(f"[Dummy GPIO] output(pin={pin}, state={state})")

    def input(self, pin):
        print(f"[Dummy GPIO] input(pin={pin}) => LOW")
        return self.LOW

    def cleanup(self):
        print("[Dummy GPIO] cleanup()")


# Instância única como no RPi.GPIO
GPIO = DummyGPIO()
