import subprocess

class OpenShellSandbox:
    def execute(self, command):
        try:
            return subprocess.check_output(command, shell=True).decode()
        except subprocess.CalledProcessError as e:
            return str(e)
