from util import get_hash
import datetime
from config import Config
import pyodbc
import logging

class Database():
    def __init__(self):
        # python3 immport pyodbc; pyodbc.drivers()
        #self.cnxn = pyodbc.connect("DRIVER={SQLite3};SERVER=localhost;DATABASE=test.db;Trusted_connection=yes")
        self.log = logging.getLogger(__name__)
        self.config = Config()
        connection_string = "DRIVER={};SERVER=localhost;DATABASE={};UID={};PWD={};PORT={}".format(
                self.config.get("database_type"), self.config.get("database_name"), self.config.get("database_user"),
                self.config.get("database_pass"), self.config.get("database_port"))
        self.cnxn = pyodbc.connect(connection_string)
        self.c = self.cnxn.cursor()
        self.log.debug("connected to databse")

    def commit(self):
        self.cnxn.commit()

    def create_tables(self):
        self.log.info("creating tables")
        with open('tables.sql') as t:
            self.c.execute(t.read())
        self.commit()
        self.log.info("created tables")

    def insert_release(self, distro, release):
        self.log.info("insert %s/%s ", distro, release)
        sql = "INSERT INTO releases VALUES (?, ?) ON CONFLICT DO NOTHING;"
        self.c.execute(sql, distro, release)
        self.commit()

    def insert_supported(self, distro, release, target, subtarget="%"):
        self.log.info("insert supported {} {} {} {}".format(distro, release, target, subtarget))
        sql = """UPDATE subtargets SET supported = true
            WHERE
                distro=? AND
                release=? AND
                target=? AND
                subtarget LIKE ?"""
        self.c.execute(sql, distro, release, target, subtarget)
        self.commit()

    def get_releases(self, distro=None):
        if not distro:
            return self.c.execute("select * from releases").fetchall()
        else:
            releases = self.c.execute("select release from releases WHERE distro=?", (distro, )).fetchall()
            respond = []
            for release in releases:
                respond.append(release[0])
            return respond

    def insert_hash(self, hash, packages):
        sql = "INSERT INTO packages_hashes VALUES (?, ?)"
        self.c.execute(sql, (hash, " ".join(packages)))
        self.commit()

    def insert_profiles(self, distro, release, target, subtarget, packages_default, profiles):
        self.log.debug("insert_profiles %s/%s/%s/%s", distro, release, target, subtarget)
        sql = "INSERT INTO packages_profile VALUES (?, ?, ?, ?, ?, ?);"
        for profile in profiles:
            print(profile)
            profile_name, profile_packages = profile
            self.log.debug("%s\n%s", profile_name, profile_packages)
            self.c.execute(sql, distro, release, target, subtarget, profile_name, profile_packages)
        self.c.execute("INSERT INTO packages_default VALUES (?, ?, ?, ?, ?);", distro, release, target, subtarget, packages_default)
        self.commit()

    def check_profile(self, distro, release, target, subtarget, profile):
        self.log.debug("check_profile %s/%s/%s/%s/%s", distro, release, target, subtarget, profile)
        self.c.execute("""SELECT 1 FROM profiles
            WHERE
                distro=? AND
                release=? AND
                target=? AND
                subtarget = ? AND
                profile = ?
            LIMIT 1;""",
            distro, release, target, subtarget, profile)
        if self.c.rowcount > 0:
            return True
        return False

    def get_profile_packages(self, distro, release, target, subtarget, profile):
        self.log.debug("get_profile_packages for %s/%s/%s/%s/%s", distro, release, target, subtarget, profile)
        self.c.execute("""select packages from packages_image
                where
                    distro = ? and
                    release = ? and
                    target = ? and
                    subtarget = ? and
                    profile = ?""",
            distro, release, target, subtarget, profile)
        response = self.c.fetchone()
        if response:
            return response[0].rstrip().split(" ")
        return response

    def insert_packages_available(self, distro, release, target, subtarget, packages):
        self.log.info("insert packages of %s/%s ", target, subtarget)
        sql = """INSERT INTO packages_available VALUES (?, ?, ?, ?, ?, ?);"""
        for package in packages:
            name, version = package
            self.c.execute(sql, distro, release, target, subtarget, name, version)
        self.commit()

    def get_packages_available(self, distro, release, target, subtarget):
        self.log.debug("get_available_packages for %s/%s/%s/%s", distro, release, target, subtarget)
        self.c.execute("""SELECT name, version
            FROM packages_available
            WHERE
                distro=? AND
                release=? AND
                target=? AND
                subtarget=?;""",
            distro, release, target, subtarget)
        response = {}
        for name, version in self.c.fetchall():
            response[name] = version
        return response

    def insert_subtargets(self, distro, release, target, subtargets):
        self.log.info("insert %s/%s ", target, " ".join(subtargets))
        sql = "INSERT INTO subtargets (distro, release, target, subtarget) VALUES (?, ?, ?, ?);"
        for subtarget in subtargets:
            self.c.execute(sql, distro, release, target, subtarget)

        self.commit()

    def get_subtargets(self, distro, release, target="%", subtarget="%"):
        self.log.debug("get_targets {} {} {} {}".format(distro, release, target, subtarget))
        return self.c.execute("""SELECT target, subtarget, supported FROM subtargets
            WHERE
                distro = ? AND
                release = ? AND
                target LIKE ? AND
                subtarget LIKE ?;""",
            distro, release, target, subtarget).fetchall()

    def check_request(self, request):
        self.log.debug("check_request")
        request_array = request.as_array()
        request_hash = get_hash(" ".join(request_array), 12)
        sql = """select status, id from image_requests
            where request_hash = ?"""
        self.c.execute(sql, request_hash)
        if self.c.rowcount > 0:
            return self.c.fetchone()
        else:
            self.log.debug("add build job")
            sql = """INSERT INTO image_requests
                (request_hash, distro, release, target, subtarget, profile, packages_hash, network_profile)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
            self.c.execute(sql, request_hash, *request_array)
            self.commit()
            return 'requested', 0

    def get_image(self, image_id):
        self.log.debug("get image %s", image_id)
        sql = "select filename, checksum, filesize from images_download, image_requests where image_requests.id = ? and image_requests.image_hash = images_download.image_hash"
        self.c.execute(sql, image_id)
        if self.c.rowcount > 0:
            return self.c.fetchone()
        else:
            return False

    def add_image(self, image_hash, image_array, checksum, filesize):
        self.log.debug("add image %s", image_array)
        sql = """INSERT INTO images
            (image_hash, distro, release, target, subtarget, profile, manifest_hash, network_profile, checksum, filesize, build_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        self.c.execute(sql, image_hash, *image_array, checksum, filesize, datetime.datetime.now())
        self.commit()
        sql = """select id from images where image_hash = ?"""
        self.c.execute(sql, image_hash)
        if self.c.rowcount > 0:
            return self.c.fetchone()[0]
        else:
            return False

    def add_manifest(self, manifest_hash):
        sql = """INSERT INTO manifest_table (hash) VALUES (?) ON CONFLICT DO NOTHING;"""
        self.c.execute(sql, manifest_hash)
        self.commit()
        sql = """select id from manifest_table where hash = ?;"""
        self.c.execute(sql, manifest_hash)
        return self.c.fetchone()[0]

    def add_manifest_packages(self, manifest_hash, packages):
        self.log.debug("add manifest packages")
        for package in packages:
            name, version = package
            sql = """INSERT INTO manifest_packages (manifest_hash, name, version) VALUES (?, ?, ?);"""
            self.c.execute(sql, manifest_hash, name, version)
        self.commit()

    def get_build_job(self):
        sql = """UPDATE image_requests
            SET status = 'building'
            FROM packages_hashes
            WHERE image_requests.packages_hash = packages_hashes.hash AND status = 'requested' AND id = (
                SELECT MIN(id)
                FROM image_requests
                WHERE status = 'requested'
                )
            RETURNING id, image_hash, distro, release, target, subtarget, profile, packages_hashes.packages, network_profile;"""
        self.c.execute(sql)
        if self.c.description:
            self.commit()
            return self.c.fetchone()
        else:
            return None

    def set_image_requests_status(self, image_request_hash, status):
        sql = """UPDATE image_requests
            SET status = ?
            WHERE image_hash = ?;"""
        self.c.execute(sql, status, image_request_hash)
        self.commit()

    def set_build_job_fail(self, image_request_hash):
        sql = """UPDATE image_requests
            SET status = 'failed'
            WHERE image_hash = ?;"""
        self.c.execute(sql, (image_request_hash, ))
        self.commit()

    def done_build_job(self, request_hash, image_hash):
        sql = """UPDATE image_requests SET
            status = 'created',
            image_hash = ?
            WHERE request_hash = ?;"""
        self.c.execute(sql, image_hash, request_hash)
        self.commit()

    def get_imagebuilder_status(self, distro, release, target, subtarget):
        sql = """select status from imagebuilder
            WHERE
                distro=? AND
                release=? AND
                target=? AND
                subtarget=?;"""
        self.c.execute(sql, distro, release, target, subtarget)
        if self.c.rowcount > 0:
            return self.c.fetchone()[0]
        else:
            sql = """INSERT INTO imagebuilder (distro, release, target, subtarget)
                VALUES (?, ?, ?, ?);"""
            self.c.execute(sql, (distro, release, target, subtarget))
            self.commit()
            return 'requested'

    def set_imagebuilder_status(self, distro, release, target, subtarget, status):
        sql = """UPDATE imagebuilder SET status = ?
            WHERE
                distro=? AND
                release=? AND
                target=? AND
                subtarget=?"""
        self.c.execute(sql, status, distro, release, target, subtarget)
        self.commit()

    def get_imagebuilder_request(self):
        sql = """UPDATE imagebuilder
            SET status = 'initialize'
            WHERE status = 'requested' and id = (
                SELECT MIN(id)
                FROM imagebuilder
                WHERE status = 'requested'
                )
            RETURNING distro, release, target, subtarget;"""
        self.c.execute(sql)
        if self.c.description:
            self.commit()
            return self.c.fetchone()
        else:
            return None

    def reset_build_requests(self):
        self.log.debug("reset building images")
        sql = "UPDATE image_requests SET status = 'requested' WHERE status = 'building'"
        self.c.execute(sql)
        self.commit()

    def worker_needed(self):
        self.log.info("get needed worker")
        sql = """select distro, release, target, subtarget
            from worker_needed, subtargets
            where worker_needed.subtarget_id = subtargets.id"""
        self.c.execute(sql)
        result = self.c.fetchone()
        self.log.debug("need worker for %s", result)
        return result

    def increase_downloads(self, image_path):
        self.log.debug("increase downloads of %s", image_path)
        sql = "UPDATE images_table SET downloads = downloads + 1 FROM images_download WHERE images_download.filename = ? and images_table.image_hash = images_download.image_hash"
        self.c.execute(sql, image_path)
        self.commit()

    def worker_register(self, name=datetime.datetime.now(), address=""):
        self.log.info("register worker %s %s", name, address)
        sql = """INSERT INTO worker (name, address, heartbeat)
            VALUES (?, ?, ?)
            RETURNING id;"""
        self.c.execute(sql, name, address, datetime.datetime.now())
        self.commit()
        return self.c.fetchone()[0]

    def worker_destroy(self, worker_id):
        self.log.info("destroy worker %s", worker_id)
        sql = """delete from worker where id = ?"""
        self.c.execute(sql, worker_id)
        self.commit()

    def worker_add_skill(self, worker_id, subtarget_id):
        self.log.info("register worker skill %s %s", worker_id, subtarget_id)
        sql = """INSERT INTO worker_skills (worker_id, subtarget_id) VALUES (?, ?)"""
        self.c.execute(sql, worker_id, subtarget_id)
        self.commit()

    def worker_heartbeat(self, worker_id):
        self.log.debug("heartbeat %s", worker_id)
        sql = "UPDATE worker SET last_seen = ? WHERE id = ?"
        self.c.execute(sql, datetime.datetime.now(), worker_id)
        self.commit()

if __name__ == "__main__":
    db = Database()
    db.create_tables()
    #print(db.worker_needed())
