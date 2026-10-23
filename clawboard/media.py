"""Image-file storage, separate from codecs and UI widgets."""
import hashlib
import os
from pathlib import Path
import tempfile
import uuid


class ImageStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def path(self, name):
        if not name or Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('invalid image filename')
        return self.directory / name

    def write(self, png):
        self.directory.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex + '.png'
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix='.capture-', dir=self.directory)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(png)
            os.replace(temporary, self.path(name))
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return name

    def read(self, name):
        return self.path(name).read_bytes()

    def remove(self, name):
        try:
            self.path(name).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass

    def same_content(self, name, png):
        try:
            return hashlib.sha256(self.read(name)).digest() == hashlib.sha256(png).digest()
        except (OSError, ValueError):
            return False
