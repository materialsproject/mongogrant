import subprocess
from uuid import uuid4


class MongodWithAuth:
    def __init__(self, port=None):
        self.started = False
        self.datadir = None
        self.logpath = None
        self.port = port

    def ensure(self):
        if self.started:
            return

        datadir = f"mongo_datadir_{uuid4()}"
        logpath = f"mongo_logpath_{uuid4()}"
        subprocess.call(f"mkdir -p {datadir}", shell=True, executable="/bin/bash")
        subprocess.call(f"touch {logpath}", shell=True, executable="/bin/bash")
        subprocess.call(f"mongod --port {self.port} --dbpath {datadir} --logpath {logpath} --auth --bind_ip_all --fork", shell=True, executable="/bin/bash")
        subprocess.call(f"mongo 127.0.0.1:{self.port}/admin --eval "
                        "'db.createUser({user:\"mongoadmin\",pwd:\"mongoadminpass\",roles:[\"root\"]});'", shell=True, executable="/bin/bash")
        self.started = True
        self.datadir = datadir
        self.logpath = logpath

    def destroy(self):
        subprocess.call(f"mongo -u mongoadmin -p mongoadminpass 127.0.0.1:{self.port}/admin --eval 'db.shutdownServer()'", shell=True, executable="/bin/bash")
        subprocess.call(f"rm -rf mongo_datadir_*", shell=True, executable="/bin/bash")
        subprocess.call(f"rm -rf mongo_logpath_*", shell=True, executable="/bin/bash")
