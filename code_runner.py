import subprocess
import tempfile
import os
def run_python_code(code, input_data):
    input_data = input_data.replace("\r\n", "\n").replace("\r", "\n")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as file:
        file.write(code)
        file_path=file.name
    try:
        result=subprocess.run(["python",file_path], input=input_data, capture_output=True, text=True, timeout=3)
        return result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return "Code took too long to run!"
    finally:
        os.remove(file_path)