import carb

def info(msg: str):
    carb.log_info(f"[Matterport] {msg}")

def warn(msg: str):
    carb.log_warn(f"[Matterport] {msg}")

def error(msg: str):
    carb.log_error(f"[Matterport] {msg}")
