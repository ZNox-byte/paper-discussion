"""PyInstaller entry point; importing this file does not start the application."""
from deepseek_survey.desktop import main

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(exc), "Paper Atlas 启动失败", 0x10)
        raise
