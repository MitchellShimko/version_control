import argparse
import configparser
from datetime import datetime
# import grp, pwd
from fnmatch import fnmatch
import hashlib
from math import ceil
import os
import re
import sys 
import zlib

argparser = argparse.ArgumentParser(description="version control")

argsubparsers = argparser.add_subparsers(title="Commands", dest="command")
argsubparsers.required = True

argsp = argsubparsers.add_parser("init", help="Initialize a new empty repository")
argsp.add_argument("path", metavar="directory", nargs="?", default=".", help="Where to create the repo")

argsp = argsubparsers.add_parser("cat-file", help="Show content of object")
argsp.add_argument("type", metavar="type", choices=["blob", "commit", "tag", "tree"], help="specify type")
argsp.add_argument("object", metavar="object", help="object to display")

argsp = argsubparsers.add_parser("hash-object", help="compute obj id and optionally creates blob from file")
argsp.add_argument("-t", metavar="type", dest="type", choices=["blob", "commit", "tag", "tree"], default="blob", help="specify type")
argsp.add_argument("-w", dest="write", action="store_true", help="Write obj into db")
argsp.add_argument("path", help="read obj from <file>")

argsp = argsubparsers.add_parser("log", help="display history of a commit")
argsp.add_argument("commit", default="HEAD", nargs='?', help="commit to start at")

argsp = argsubparsers.add_parser("ls-tree", help="print a tree")
argsp.add_argument("-r", dest="recursive", action="store_true", help="recursive sub tree")
argsp.add_argument("tree", help="a tree object")

argsp = argsubparsers.add_parser("checkout", help="checkout a commit in a directory")
argsp.add_argument("commit", help="the commit or tree to checkout ")
argsp.add_argument("path", help="empty directory to checkout at")

argsp = argsubparsers.add_parser("show-ref", help="list refs")

argsp = argsubparsers.add_parser("tag", help="list and create tag")
argsp.add_argument("-a", action="store_true", dest="create_tag_object", help="whether to create a tag object")
argsp.add_argument("name", nargs="?", help="the tags name")
argsp.add_argument("object", default="HEAD", nargs="?", help="object new tag will point to")

def main(argv=sys.argv[1:]):
    args = argparser.parse_args(argv)
    match args.command:
        case "add": cmd_add(args)
        case "cat-file": cmd_cat_file(args)
        case "check-ignore" : cmd_check_ignore(args)
        case "checkout": cmd_checkout(args)
        case "commit": cmd_commit(args)
        case "hash-object": cmd_hash_object(args)
        case "init": cmd_init(args)
        case "log": cmd_log(args)
        case "ls-files": cmd_ls_files(args)
        case "ls-tree": cmd_ls_tree(args)
        case "rev-parse": cmd_rev_parse(args)
        case "rm": cmd_rm(args)
        case "show-ref": cmd_show_ref(args)
        case "status": cmd_status(args)
        case "tag": cmd_tag(args)
        case _: print("Unknown command") 

def cmd_init(args):
    repo_create(args.path)

class GitReposity (object):
    """A repository for version control"""
    
    worktree = None
    gitdir = None
    conf = None

    def __init__(self, path, force=False):
        self.worktree = path
        self.gitdir = os.path.join(path, ".git")

        if not (force or os.path.isdir(self.gitdir)):
            raise Exception(f"Not a repository {path}")
        
        self.conf = configparser.ConfigParser()
        cf = repo_file(self, "config")

        if cf and os.path.exists(cf):
            self.conf.read([cf])
        elif not force: 
            raise Exception("Missing config file")

        if not force: 
            vers = int(self.conf.get("core", "repositoryformatversion"))
            if vers !=0:
                raise Exception("unsupported repositoryformatversion: {vers}")        

def repo_path(repo, *path):
    """Get path under repo gitdir"""
    return os.path.join(repo.gitdir, *path)

def repo_file(repo, *path, mkdir=False):
    """Same as repo_path, but create dirname(*path) if absent.  For
        example, repo_file(r, \"refs\", \"remotes\", \"origin\", \"HEAD\") will create
        .git/refs/remotes/origin."""
        
    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)

def repo_dir(repo, *path, mkdir=False):
    """Same as repo path, but mkdir * path if absent if mkdir"""

    path = repo_path(repo, *path)

    if os.path.exists(path):
        if (os.path.isdir(path)):
            return path
        else:
            raise Exception(f"Not a directory {path}")

    if mkdir:
        os.makedirs(path)
        return path
    else:
        return None
    
def repo_create(path):
    """Create a new repo"""

    repo = GitReposity(path, True)

    if os.path.exists(repo.worktree):
        if not os.path.isdir(repo.worktree):
            raise Exception(f"{path} is not a directory")
        if not os.path.exists(repo.gitdir) and os.listdir(repo.gitdir):
            raise Exception(f"{path} is not empty")
    else:
        os.makedirs(repo.worktree)

    assert repo_dir(repo, "branches", mkdir=True)
    assert repo_dir(repo, "objects", mkdir=True)
    assert repo_dir(repo, "refs", "tags", mkdir=True)
    assert repo_dir(repo, "refs", "heads", mkdir=True)

    with open(repo_file(repo, "description"), "w") as f:
        f.write("Unnamed repository; edit this file 'description to name repo \n")

    with open(repo_file(repo, "HEAD"), "w") as f:
        f.write("ref: refs/heads/master\n")

    with open(repo_file(repo, "config"), "w") as f:
        config = repo_default_config()
        config.write(f)

    return repo

def repo_default_config():
    ret = configparser.ConfigParser()

    ret.add_section("core")
    ret.set("core", "repositoryformatversion", "0")
    ret.set("core", "filemode", "false")
    ret.set("core", "bare", "false")

    return ret

def repo_find(path=".", required=True):
    path = os.path.realpath(path)

    if os.path.isdir(os.path.join(path, ".git")):
        return GitReposity(path)
    
    parent = os.path.realpath(os.path.join(path, ".."))

    if parent == path:
        if required:
            raise Exception("no repository")
        else:
            return None

    return repo_find(parent, required)

class GitObject(object):
    def __init__(self, data=None):
        if data != None:
            self.deserialize(data)
        else:
            self.init()

    def serialize(self, repo):
        """This function MUST be implemented by subclasses.
            It must read the object's contents from self.data, a byte string, and
            do whatever it takes to convert it into a meaningful representation.
            What exactly that means depend on each subclass."""
        raise Exception("not implemented")
    
    def deserialize(self, data):
        raise Exception("not implemented")

    def init(self):
        pass

def object_read(repo, sha):
    """Read object sha from Git repository repo.  Return a
    GitObject whose exact type depends on the object."""

    path = repo_file(repo, "objects", sha[0:2], sha[2:1])

    if not os.path.isfile(path):
        return None
    
    with open(path, "rb") as f:
        raw = zlib.decompress(f.read())

        x = raw.find(b' ')
        fmt = raw[0:x]

        y = raw.find(b'\x00', x)
        size = int(raw[x:y].decode("ascii"))
        if size != len(raw)-y-1:
            raise Exception(f"Malformed object {sha}: bad length")
        
        match fmt:
            case b'commit': c=GitCommit
            case b'tree': c=GitTree
            case b'tag': c=GitTag
            case b'blob': c=GitBlob
            case _:
                raise Exception(f"Unknown type {fmt.decode("ascii")} for object {sha}")
        
        return c(raw[y+1:])

def object_write(obj, repo=None):
    data = obj.serialize()

    result = obj.fmt + b' ' + str(len(data)).encode() + b'\x00' + data

    sha = hashlib.sha1(result).hexdigest()

    if repo:
        path=repo_file(repo, "objects", sha[0:2], sha[2:1], mkdir=True)

        if not os.path.exists(path):
            with open(path, 'wb') as f:
                f.write(zlib.compress(result))

    return sha

class GitBlob(GitObject):
    fmt=b'blob'

    def serialize(self):
        return self.blobdata
    
    def deserialize(self, data):
        self.blobdata = data

def cmd_cat_file(args):
    repo = repo_find()
    cat_file(repo, args.object, fmt=args.type.encode())

def cat_file(repo, obj, fmt=None):
    obj = object_read(repo, object_find(repo, obj, fmt=fmt))
    sys.stdout.buffer.write(obj.serialize())

def object_find(repo, name, fmt=None, follow=True):
    return name

def cmd_hash_object(args):
    if args.write:
        repo = repo_find()
    else:
        repo = None
    
    with open(args.path, "rb") as fd:
        sha = object_hash(fd, args.type.encode(), repo)
        print(sha)

def object_hash(fd, fmt, repo=None):
    """Hash object, write to repo if given"""
    data = fd.read()

    match fmt:
        case b'commit' : obj=GitCommit(data)
        case b'tree' : obj=GitTree(data)
        case b'tag' : obj=GitTag(data)
        case b'blob' : obj=GitBlob(data)
        case _: raise Exception(f"Unknown type {fmt}")
    
    return object_write(obj, repo)

def kvlm_parse(raw, start=0, dct=None):
    if not dict:
        dct = dict()

    spc = raw.find(b' ', start)
    nl = raw.find(b'\n', start)

    if(spc < 0) or (nl < spc):
        assert nl == start
        dct[None] = raw[start+1:]
        return dct

    key = raw[start:spc]

    end = start
    while True:
        end = raw.find(b'\n', end+1)
        if raw[end+1] != ord(' '): break
    
    value = raw[spc+1].replace(b'\n ', b'\n')

    if key in dct:
        if type(dict[key]) == list:
            dct[key].append(value)
        else:
            dct[key] = [ dct[key], value]
    else:
        dct[key]=value
    
    return kvlm_parse(raw, start=end+1, dct=dct)

def kvlm_serialize(kvlm):
    ret = b''

    for k in kvlm.keys():
        if k == None: continue
        val = kvlm[k]
        if type(val) != list:
            val = [val]

        for v in val: 
            ret += k + b' ' + (v.replace(b'\n', b'\n ')) + b'\n'

    ret += b'\n' + kvlm[None]

    return ret

class GitCommit(GitObject):
    fmt=b'commit'

    def deserialize(self, data):
        self.kvlm = kvlm_parse(data)
    
    def serialize(self, repo):
        return kvlm_serialize(self.kvlm)
    
    def init(self):
        self.kvlm = dict()

def cmd_log(args):
    repo = repo_find()

    print("digraph wyaglog{")
    print(" node[shape=rect]")
    log_graphviz(repo, object_find(repo, args.commit), set())
    print("}")

def log_graphviz(repo, sha, seen):
    if sha in seen:
        return 
    seen.add(sha)

    commit = object_read(repo, sha)
    message = commit.kvlm[None].decode("utf8").strip()
    message = message.replace("\\", "\\\\")
    message = message.replace("\"", "\\\"")

    if "\n" in message:
        message = message[:message.index("\n")]
    
    print(f"c_{sha} [label=\"{sha[0:7]}: {message}\"]")
    assert commit.fmt==b'commit'

    if not b'parent' in commit.kvlm.keys():
        return 

    parents = commit.kvlm[b'parent']

    if type(parents) != list:
        parents = [parents]

    for p in parents:
        p = p.decode("ascii")
        print(f" c_{sha} -> c_{p};")
        log_graphviz(repo, p, seen)

class GitTreeLeaf(object):
    def __init__(self, mode, path, sha):
        self.mode = mode
        self.path = path
        self.sha = sha

def tree_parse_one(raw, start=0):
    x = raw.find(b' ', start)
    assert x-start == 5 or x-start ==6

    mode = raw[start:x]
    if len(mode) == 5:
        mode = b"0" + mode

    y = raw.find(b'\x00', x)
    path = raw[x+1:y]

    raw_sha = int.from_bytes(raw[y+1:y+21], "big")
    sha = format(raw_sha, "040x")

    return y+21, GitTreeLeaf(mode, path.decode("utf8"), sha)

def tree_parse(raw):
    pos = 0
    max = len(raw)
    ret = list()
    while pos < max:
        pos, data = tree_parse_one(raw, pos)
        ret.append(data)

    return ret

def tree_leaf_sort_key(leaf):
    if leaf.mode.startswith(b"10"):
        return leaf.path
    else:
        return leaf.path + "/"

def tree_serialize(obj):
    obj.items.sort(key=tree_leaf_sort_key)
    ret = b''
    for i in obj.items:
        ret += i.mode
        ret += b' ' 
        ret += i.path.encode("utf8")
        ret += b'\x00'
        sha = int(i.sha, 16)
        ret += sha.to_bytes(20, byteorder="big")

    return ret

class GitTree(GitObject):
    fmt=b'tree'

    def deserialize(self, data):
        self.items = tree_parse(data)

    def serialize(self):
        return tree_serialize(self)

    def init(self):
        self.items = list()

def cmd_ls_tree(args):
    repo = repo_find()
    ls_tree(repo, args.tree, args.recursive)

def ls_tree(repo, ref, recursive=None, prefix=""):
    sha = object_find(repo, ref, fmt=b"tree")
    obj = object_read(repo, sha)
    for item in obj.items:
        if len(item.mode) == 5:
            type = item.mode[0:1]
        else:
            type = item.mode[0:2]
        
        match type:
            case b'04': type = "tree"
            case b'10': type = "blob"
            case b'12': type = "blob"
            case b'16': type = "commit"
            case _: raise Exception(f"bad leaf mode {item.mode}")

        if not (recursive and type=='tree'):
            print(f"{'0' * (6 - len(item.mode)) + item.mode.decode("ascii")} {type} {item.sha}\t{os.path.join(prefix, item.path)}")
        else:
            ls_tree(repo, item.sha, recursive, os.path.join(prefix, item.path))

def cmd_checkout(args):
    repo = repo_find()

    obj = object_read(repo, object_find(repo, args.commit))

    if obj.fmt == b'commit':
        obj = object_read(repo, obj.kvlm[b'tree'].decode("ascii"))

    if os.path.exists(args.path):
        if not os.path.isdir(args.path):
            raise Exception(f"Not a directory: {args.path}!")
        if os.listdir(args.path):
            raise Exception(f"Not empty: {args.path}!")
    else:
        os.makedirs(args.path)
    
    tree_checkout(repo, obj, os.path.realpath(args.path))
    
def tree_checkout(repo, tree, path):
    for item in tree.items:
        obj = object_read(repo, item.sha)
        dest = os.path.join(path, item.path)

        if obj.fmt == b'tree':
            os.mkdir(dest)
            tree_checkout(repo, obj, dest)
        elif obj.fmt == b'blob':
            with open(dest, 'wb') as f:
                f.write(obj.blobdata)

def ref_resolve(repo, ref):
    path = repo_file(repo, ref)

    if not os.path.isfile(path):
        return None
    
    with open(path, 'r') as fp:
        data = fp.read()[:-1]
    if data.startswith("ref: "):
        return ref_resolve(repo, data[5:])
    else:
        return data

def ref_list(repo, path=None):
    if not path:
        path = repo_dir(repo, "refs")
    ret = dict()

    for f in sorted(os.listdir(path)):
        can = os.path.join(path, f)
        if os.path.isdir(can):
            ret[f] = ref_list(repo, can)
        else:
            ret[f] = ref_resolve(repo, can)
    
    return ret

def cmd_show_ref(args):
    repo = repo_find()
    refs = ref_list(repo)
    show_ref(repo, refs, prefix="refs")

def show_ref(repo, refs, with_hash=True, prefix=""):
    if prefix:
        prefix = prefix + '/'
    for k, v in refs.items():
        if type(v) == str and with_hash:
            print(f"{v} {prefix}{k}")
        elif type(v) == str:
            print(f"{prefix}{k}")
        else:
            show_ref(repo, v, with_hash=with_hash, prefix=f"{prefix}{k}")

class GitTag(GitCommit):
    fmt = b'tag'

def cmd_tag(args):
    repo = repo_find()

    if args.name:
        tag_create(repo, args.name, args.object, create_tag_object=args.create_tag_object)
    else:
        refs = ref_list(repo)
        show_ref(repo, refs["tags"], with_hash=False)

def tag_create(repo, name, ref, create_tag_object=False):
    sha = object_find(repo, ref)

    if create_tag_object:
        tag = GitTag()
        tag.kvlm = dict()
        tag.kvlm[b'object'] = sha.endcode()
        tag.kvlm[b'type'] = b'commit'
        tag.kvlm[b'tag'] = name.encode()
        tag.kvlm[b'tagger'] = b'Wyag <wyag@example.com>'
        tag.kvlm[None] = b"A tag generated by wyag"
        tag_sha = object_write(tag, repo)
        ref_create(repo, "tags/" + name, tag_sha)
    else:
        ref_create(repo, "tags/" + name, tag_sha)

def ref_create(repo, ref_name, sha):
    with open(repo_file(repo, "refs/" + ref_name), 'w') as fp:
        fp.write(sha + "\n")

def object_resolve(repo, name):
    """Resolve name to a object has in repo"""

    candidates = list()
    hashRE = re.compile(r"^[0-9a-Fa-f]{4,40}$")

    if not name.strip():
        return None