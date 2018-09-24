#!/usr/bin/env python3

import os
import hashlib
import zipfile
import json
import re
from typing import List, Dict
from subprocess import call
from flask import Flask, flash, request, redirect, send_from_directory, send_file
from werkzeug.utils import secure_filename
from werkzeug.exceptions import BadRequest
from peewee import ForeignKeyField, CharField, Model
from playhouse.sqlite_ext import SqliteExtDatabase
from pakk import pakk_files

FIRST_INIT = not os.path.exists("server.db")

os.makedirs("./build", exist_ok=True)
os.makedirs("./dist", exist_ok=True)
os.makedirs("./releases", exist_ok=True)
os.makedirs("./temp/uploads", exist_ok=True)
os.makedirs("./temp/unzipped", exist_ok=True)
# ensure server.db exists
if FIRST_INIT:
    with open("server.db", "w") as server_file:
        pass

CONN = SqliteExtDatabase("./server.db", pragmas={
    'journal_mode': 'wal',
    'cache_size': -1 * 64000,  # 64MB
    'foreign_keys': 1,
    'ignore_check_constraints': 0,
    'synchronous': 0})

APP = Flask(__name__)

class BaseModel(Model):
    class Meta:
        database = CONN

class Product(BaseModel):
    identifier = CharField(unique=True)
    name = CharField()

class Release(BaseModel):
    product = ForeignKeyField(Product, backref="releases")
    version = CharField()
    def get_path(self, operating_system: str) -> 'ReleasePath':
        for path in self.paths:
            if path.operating_system == operating_system:
                return path
        return None

class ReleasePath(BaseModel):
    release = ForeignKeyField(Release, backref="paths")
    operating_system = CharField()
    installer_path = CharField()
    dist_path = CharField()

CONN.connect()
with open("./update_embed.py", "r") as update_embed:
    UPDATE_EMBED = update_embed.read()
if FIRST_INIT:
    CONN.create_tables([Product, Release, ReleasePath])

"""
Folder structure on the server
./
    server.py
    server.db
    build/
        ...temp files...
    dist/
        ...temp files...
    releases/
        my_app/
            0.0.0/
                myapp 0.0.0.dmg
            1.0.0/
                myapp 1.0.0.dmg
        ...etc...
    temp/
        uploads/
            ...uploaded temp files...
        unzipped/
"""

def make_pakkage(product: Product, icon: str, password: str, app: str, pakked_resources: List[str]=None, unpakked_resources: List[str]=None, plist: Dict[str, str]=None) -> Release:
    key = hashlib.sha256(password.encode("utf-8")).digest()

    print("pakking")
    # Create Pakk out of the resources requested to be pakked
    if len(pakked_resources) > 0:
        pakk_files(key, pakked_resources, "./build/pakk.pakk")

    if not unpakked_resources:
        unpakked_resources = []
    
    # unpakked_resources is used to identify files and folders that need to be moved to the app's Resources folders
    # and we need to use Pakk in the deployed software, so add it to the unpakked_resources.
    if len(pakked_resources) > 0:
        unpakked_resources.append("./build/pakk.pakk")
        
    version = plist["CFBundleShortVersionString"]
    if not version:
        version = "0.0.0"

    if icon:
        icon = f"'iconfile': '{icon}',"
    else:
        icon = ""

    # prepend autoupdate utility to startup app
    embedded = UPDATE_EMBED.replace("[%__pakk_server__%]", request.url_root)
    embedded = embedded.replace("[%__pakk_product__%]", product.identifier)
    embedded = embedded.replace("[%__pakk_version__%]", version)

    with open(app, "r") as original_app: original_data = original_app.read()
    with open(app, "w") as modified_app: modified_app.write(f"{embedded}\n{original_data}")

    print("building")
    setup_path = os.path.join(".", "temp", f"setup_{product.identifier}_{version}.py")
    with open(setup_path, "w") as setup_file:
        setup_file.writelines(f"""
from setuptools import setup

APP = ['{app}']
DATA_FILES = []
OPTIONS = {{
    {icon}
    "resources": {json.dumps(unpakked_resources)},
    "plist": {json.dumps(plist)}
}}

setup(
    name="{product.name}",
    app=APP,
    data_files=DATA_FILES,
    options={{'py2app': OPTIONS}},
    setup_requires=['py2app'],
    install_requires=[
        "pycrypto"
    ],
)
        """)

    # Build app
    os.makedirs(f"./dist/{product.identifier}", exist_ok=True)
    call(["python3", setup_path, "py2app", f"--dist-dir=./dist/{product.identifier}"])

    # package macOS executable into DMG for distribution.
    print("packaging")
    dist_app_path = os.path.join(".", "dist", product.identifier, f"{product.name}.app")
    release_version_path = os.path.join(".", "releases", product.identifier, version)
    release_identifer_dmg_path = os.path.join(release_version_path, f"{product.name} {version}.dmg")
    release_name_dmg_path = os.path.join(release_version_path, f"{product.name}.dmg")
    release_name_dist_path = os.path.join(release_version_path, f"{product.name}.zip")

    os.makedirs(release_version_path, exist_ok=True)
    call(["create-dmg", dist_app_path, release_version_path, "--overwrite"])
    call(["mv", release_identifer_dmg_path, release_name_dmg_path])
    with zipfile.ZipFile(release_name_dist_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(dist_app_path):
            for file in files:
                filename = os.path.join(root, file)
                arcname = filename[len(dist_app_path):]
                zipf.write(filename, arcname=arcname)

    release = Release.create(product=product, version=version)
    ReleasePath.create(release=release, operating_system="darwin", dist_path=release_name_dist_path, installer_path=release_name_dmg_path)
    # TODO ReleasePath(release=release, operating_system="win32", path=release_name_dmg_path)
    # TODO ReleasePath(release=release, operating_system="linux", path=release_name_dmg_path)

    print("done pakkaging")
    return release

def allowed_file(filename: str):
    return "." in filename and filename.rsplit(".", 1)[1].lower() == "zip"

def cmp(a, b):
    return (a > b) - (a < b)

def compare_versions(left: str, right: str) -> int:
    def normalize(v):
        return [int(x) for x in re.sub(r'(\.0+)*$', '', v).split(".")]
    return cmp(normalize(left), normalize(right))

def get_latest_release(identifier: str) -> Release:
    releases = Release.select().join(Product).where(Product.identifier == identifier)
    latest_release = releases[0]
    release: Release
    for release in releases:
        if compare_versions(latest_release.version, release.version) < 0:
            latest_release = release

    return latest_release

@APP.route("/", methods=["GET"])
def index():
    return """
    <!doctype html>
    <html>
    <head>
        <title>Upload new File</title>
    </head>
    <body>
        <h1>Upload new File</h1>
        <form action='/pakkage' method=post enctype=multipart/form-data>
            identifier: <input type=textbox name=identifier> <br>
            name: <input type=textbox name=name> <br>
            password: <input type=textbox name=password> <br>
            app: <input type=textbox name=app> <br>
            pakked: <input type=textbox name=pakked> <br>
            unpakked: <input type=textbox name=unpakked> <br>
            plist: <input type=textbox name=plist> <br>
            <input type=file name=file> <br>
            <input type=submit value=Upload>
        </form>
    </body>
    </html>
    """

@APP.route("/releases/<path:path>", methods=["GET"])
def get_release(path: str):
    return send_from_directory("./releases", path)

@APP.route("/products", methods=["GET", "PUT", "DELETE"])
def products():
    if request.method == "GET":
        return list(Product.select())
    elif request.method == "PUT":
        identifier = request.form["identifier"]
        if len(Product.select().where(Product.identifier == identifier)) > 0:
            return BadRequest(f"There is already a product with the identifier {identifier}")

        product = Product(identifier=identifier, name=request.form["name"])
        product.save()
        return product
    elif request.method == "DELETE":
        identifier = request.form["identifier"]
        product = Product.select().where(Product.identifier == identifier).get_or_none()
        if not product:
            return BadRequest(f"No product with the identifier {identifier}")
        
        product.delete()

@APP.route("/updater", methods=["GET"])
def get_updater():
    return send_file("./updater.py")

@APP.route("/product/<identifier>/latest/<operating_system>", methods=["GET"])
def get_product_latest(identifier: str, operating_system: str):
    latest_release = get_latest_release(identifier)
    latest_release_path = latest_release.get_path(operating_system)
    return send_file(latest_release_path.dist_path)

@APP.route("/product/<identifier>/latest/version", methods=["GET"])
def get_product_latest_version(identifier: str):
    return get_latest_release(identifier).version

@APP.route("/pakkage", methods=["POST"])
def post_make_pakkage():
    if "file" not in request.files:
        flash("No file part")
        return redirect(request.url)
    
    file = request.files["file"]
    if file.filename == "":
        flash("No selected file")
        return redirect(request.url)

    if file and allowed_file(file.filename):
        # save uploaded file with a unique name into the temp uploads folder
        filename = os.path.join("./temp/uploads", secure_filename(file.filename))

        used_filename = filename
        appender = 0
        while os.path.exists(used_filename):
            used_filename = f"{filename}{appender}"
            appender += 1
        
        file.save(used_filename)
        
        # unzip the uploaded file into the temp unzipped folder
        unzipped_path = os.path.join("./temp/unzipped", f"{secure_filename(file.filename)}{appender}")
        with zipfile.ZipFile(used_filename, 'r') as in_zip:
            in_zip.extractall(unzipped_path)

        # create a pakkage from the zip file and the provided values
        product_identifier = request.form["identifier"]
        product_name = request.form["name"]
        plist = json.loads(request.form["plist"])
        version = plist["CFBundleShortVersionString"]

        product = Product.get_or_none(Product.identifier == product_identifier)
        if not product:
            product = Product.create(identifier=product_identifier, name=product_name)
        elif len(product.releases.where(Release.version == version)) > 0:
            return BadRequest(f"There is already a release of {product_identifier} with version {version}")

        app = os.path.join(unzipped_path, request.form["app"])
        pakked = []
        if len(request.form["pakked"].strip()) > 0:
            pakked = [os.path.join(unzipped_path, x) for x in request.form["pakked"].split(",")]

        unpakked = []
        if len(request.form["unpakked"].strip()) > 0:
            unpakked = [os.path.join(unzipped_path, x) for x in request.form["unpakked"].split(",")]

        icon = os.path.join(unzipped_path, "pakkicon.icns")
        if not os.path.isfile(icon):
            icon = None
        
        release = make_pakkage(product, icon, request.form["password"], app, pakked, unpakked, plist)

        releases = {
            "darwin": release.get_path("darwin").installer_path,
            # "win32": release.get_path("win32").installer_path,
            # "linux": info.paths["linux"].path
        }

        return json.dumps(releases)

    return BadRequest()
