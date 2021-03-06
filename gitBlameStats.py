# Copyright (c) 2014 Brad Neuman

# This file holds the code that interacts with git, without any other dependencies

import subprocess
from pprint import pprint

class BlameStats:
    "Interface to git to collect statistics about blame lines for a given repository. The main function"
    " is GetCommitStats()"

    def __init__(self, repo_path, debug = False):
        self.repo = repo_path
        self.debug = debug
        self.git_cmd = ['git', '-C', self.repo, '--no-pager']

    def dprint(self, s):
        "internal helper for printing debug info"
        if self.debug:
            print(" # DEBUG: '%s'" % s)


    def GetDiffStats(self, rev, lastRev):
        "return a tuple of 4 things:\n"
        "  * a dictionary of old filename -> list of tuple (lineNum, numberOfLines). These are the lines\n"
        "    in the old file that were deleted by this commit\n"
        "  * a dictionary of new filename -> number of lines added by the author\n"
        "  * a dictionary of new filename -> number of lines removed by the author\n"
        "  * a list of tuples of file renames (oldFilename, newFilename)"
        ""
        "NOTE: this assumes the history is totally flat, and pretends that rev happened directly on top of lastRev"

        if lastRev:
            cmd = self.git_cmd + ['diff',
                                  '-C', # find copies
                                  '-M', # find moves
                                  '-U0', # don't print extra lines around diff
                                  '-w', # ignore whitespace
                                  '--no-color',
                                  lastRev,
                                  rev]
        else:
            cmd = self.git_cmd + ['show', # display commit message and diff
                                  '-C', # find copies
                                  '-M', # find moves
                                  '-w', # ignore whitespace
                                  '-U0', # don't print extra lines around diff
                                  '--ignore-submodules',
                                  '--no-color',
                                  rev]

        oldLinesPerFile = {}
        numNewLinesPerFile = {} # key is new file
        numDeletedLinesPerFile = {} # key is new file
        renames = []

        # current parsing state. TODO: enum?
        state_diff_start = 0
        state_diff_header = 1
        state_diff_body = 2

        state = state_diff_start

        oldFile = None
        newFile = None

        data = subprocess.check_output(cmd)
        for line in data.split('\n'):
            if self.debug:
                print line

            if len(line)>0:
                if line[:4] == "diff":
                    oldFile = None
                    newFile = None
                    state = state_diff_header
                    continue

                if line[:2] == '@@':
                    state = state_diff_body

                if state == state_diff_header:
                    if line[:3] == '---':
                        if line[:14] != "--- /dev/null":
                            oldFile = line[6:]
                            self.dprint(" old file is %s" % oldFile)
                            continue
                    elif line[:3] == '+++':
                        if line[:14] != "+++ /dev/null":
                            newFile = line[6:]
                            self.dprint(" new file is %s" % newFile)
                            # this comes second
                            if oldFile and oldFile != newFile:
                                renames.append( (oldFile, newFile) )
                            continue

                elif state == state_diff_body:
                    if line[:3] == '@@@':
                        self.dprint('merge commit! shouldnt happen, returning empty')
                        return ({}, {}, {}, [])

                    elif line[:2] == '@@':
                        # find ending @@
                        endIdx = line.find('@@', 3)
                        if endIdx > 2:
                            for lineChunk in line[3:endIdx-1].split(' '):
                                commaIdx = lineChunk.find(',')
                                if commaIdx >= 0:
                                    try:
                                        newLineInfo = (int(lineChunk[1:commaIdx]), int(lineChunk[commaIdx+1:]))
                                    except ValueError:
                                        print("ERROR: value error! couldn't parse '%s, %s' from line %s" % (
                                            lineChunk[1:commaIdx],
                                            lineChunk[commaIdx+1:],
                                            line) )
                                        return None
                                else:
                                    try:
                                        # if there's one line, no comma is printed
                                        newLineInfo = (int(lineChunk[1:]), 1)
                                    except ValueError:
                                        print("ERROR: value error! couldn't parse '%s' from line '%s'" % (
                                            lineChunk[1:],
                                            line))
                                        return None


                                if newLineInfo[1] > 0:
                                    if lineChunk[0] == '-':
                                        if oldFile not in oldLinesPerFile:
                                            oldLinesPerFile[oldFile] = []
                                        oldLinesPerFile[oldFile].append(newLineInfo)
                                        self.dprint("oldLines (%d, %d)" % (newLineInfo[0], newLineInfo[1]))

                    # these are at the bottom ebecause they could fuck up with '---' or '+++'
                    elif line[0] == '+':
                        self.dprint("line added")
                        nc = 0
                        if newFile in numNewLinesPerFile:
                            nc = numNewLinesPerFile[newFile]
                        numNewLinesPerFile[newFile] = nc + 1
                    elif line[0] == '-':
                        self.dprint("line removed")
                        dc = 0
                        if oldFile in numDeletedLinesPerFile:
                            dc = numDeletedLinesPerFile[oldFile]
                        numDeletedLinesPerFile[oldFile] = dc + 1

        return (oldLinesPerFile, numNewLinesPerFile, numDeletedLinesPerFile, renames)


    def GetOldBlameStats(self, rev, lastRev, oldLinesPerFile):
        "Given a revision and some info on lines in the old file from diff stats,\n"
        "  return a dictionary of filename -> list of (author, lines lost)"

        if lastRev == None:
            return {}

        blame_cmd = self.git_cmd + ['blame',
                                    '-w', # ignore whitespace
                                    '-C', # find copies
                                    '-M', # find moves
                                    '--line-porcelain' # print info for each line
                                   ]

        linesLost = {}

        for filename in oldLinesPerFile:
            self.dprint("getting stats for '%s'" % filename)
            linesLost[filename] = []

            cmd = blame_cmd + \
                  [ "-L %d,+%d"% (startLine, numLines) for startLine, numLines in oldLinesPerFile[filename]] + \
                  [lastRev, '--', filename]

            linesLostPerAuthor = {}

            self.dprint(" ".join(cmd))
            for line in subprocess.check_output(cmd).split('\n'):
                if line[:7] == "author ":
                    author = line[7:]
                    self.dprint("%s lost a line" % author)
                    ac = 0
                    if author in linesLostPerAuthor:
                        ac = linesLostPerAuthor[author]
                    linesLostPerAuthor[author] = ac + 1

            for author in linesLostPerAuthor:
                linesLost[filename].append( (author, linesLostPerAuthor[author]) )

        return linesLost


    def GetCommitAuthor(self, rev):
        "return the author of the commit specified by rev"
        
        cmd = self.git_cmd + ['log',
                              '-n', '1', # only show one enry
                              '--format=%aN', # just print author name
                              rev]
        revAuthor = subprocess.check_output(cmd)
        if revAuthor[-1] == '\n':
            revAuthor = revAuthor[:-1]

        self.dprint("author of revision is '%s'" % revAuthor)

        return revAuthor


    def GetParents(self, rev):
        "returns a list of parents of rev. Maybe contain 0, 1, or 2 results"
        
        cmd = self.git_cmd + ['log',
                              '-n', '1', # only one entry
                              '--pretty=format:%P', # just show parents
                              rev]

        data = subprocess.check_output(cmd)
        return data.split(' ')


    def GetFullBlames(self, rev, filenames):
        "given a current revision and a list of filenames, return"
        "a dict of filename -> author -> num_lines"

        blame_cmd = self.git_cmd + ['blame',
                                    '-w', # ignore whitespace
                                    '-C', # find copies
                                    '-M', # find moves
                                    '--line-porcelain', # print info for each line
                                    rev
                                   ]

        ret = {}

        for filename in filenames:
            cmd = blame_cmd + ['--', filename]
            self.dprint(" ".join(cmd))

            try:
                data = subprocess.check_output(cmd)
            except subprocess.CalledProcessError as cpe:
                print "Warning: git failed"
                print cpe
                print "continuing anyway..."
                continue

            ret[filename] = {}

            for line in data.split('\n'):
                if line[:7] == "author ":
                    author = line[7:]
                    ac = 0
                    if author in ret[filename]:
                        ac = ret[filename][author]
                    ret[filename][author] = ac + 1

        return ret

    def GetFilesTouchedByCommit(self, rev):
        "returns a tuple of:"
        " * a list of filenames that exist in rev that have changes"
        " * a list of filenames that rev deleted"

        cmd = self.git_cmd + ['show', # display commit message and diff
                              '-M', # find moves
                              '--no-color',
                              '--ignore-submodules',
                              rev]

        oldFile = None
        newFile = None
        header = False

        files = []
        deletedFiles = []

        renamed_from = 'rename from '
        renamed_to = 'rename to '

        self.dprint(' '.join(cmd))

        data = subprocess.check_output(cmd)
        for line in data.split('\n'):
            if len(line)>0:
                if line[:4] == "diff":
                    header = True
                    oldFile = None
                    newFile = None
                if line[:2] == '@@':
                    header = False

                if header:
                    if line[:3] == '---':
                        if line[:14] != "--- /dev/null":
                            oldFile = line[6:]
                            continue
                    elif line[:3] == '+++':
                        if line[:14] != "+++ /dev/null":
                            newFile = line[6:]
                            files.append(newFile.strip())
                        else:
                            deletedFiles.append(oldFile.strip())

                    elif line[:len(renamed_from)] == renamed_from:
                        deletedFiles.append(line[len(renamed_from):])
                    elif line[:len(renamed_to)] == renamed_to:
                        files.append(line[len(renamed_to):])

        return files, deletedFiles




    def GetCommitStats(self, rev):
        "take a given revision and return a dictionary of:\n"
        "    new filename -> author -> numberOfLines"
        "a filename with no authors means the file was deleted"

        newFiles, deletedFiles = self.GetFilesTouchedByCommit(rev)

        self.dprint("new files: %s" % newFiles)

        blames = self.GetFullBlames(rev, newFiles)

        for filename in deletedFiles:
            if filename in blames:
                print "ERROR: file '%s' was deleted but also edited" % filename
            blames[filename] = {}

        return blames


    def GetCommitStats_broken(self, rev, lastRev):
        "take a given revision and return a dictionary of:\n"
        "    new filename -> author -> (lines added, lines removed)"
        "lastRev should be the immediately proceeding commit to rev"
        " THIS IS BROKEN! only works for repos with no merges"
        

        oldLinesPerFile, numNewLinesPerFile, numDeletedLinesPerFile, renames = self.GetDiffStats(rev, lastRev)

        if self.debug:
            pprint(oldLinesPerFile)
            pprint(numNewLinesPerFile)
            pprint(numDeletedLinesPerFile)
            pprint(renames)

        linesLost = self.GetOldBlameStats(rev, lastRev, oldLinesPerFile)

        if self.debug:
            pprint(linesLost)

        for filename in numDeletedLinesPerFile:
            total1 = numDeletedLinesPerFile[filename]
            if filename in linesLost:
                total2 = sum([num for auth,num in linesLost[filename]])
                if total1 != total2:
                    print "ERROR: number of blame lines and deleted lines differs for commit '%s'" % rev

        ret = {}

        revAuthor = self.GetCommitAuthor(rev)

        # first add the lines that were deleted
        for filename in linesLost:
            ret[filename] = {}

            if filename in linesLost:
                for author, lines in linesLost[filename]:
                    self.dprint("    -= %d to '%s'" % (lines, author))
                    ret[filename][author] = (0, lines)

        # now add lines added by us for each filename
        for filename in numNewLinesPerFile:
            if filename not in ret:
                ret[filename] = {}

            if revAuthor not in ret[filename]:
                ret[filename][revAuthor] = (numNewLinesPerFile[filename], 0)
            else:
                ret[filename][revAuthor] = (numNewLinesPerFile[filename], ret[filename][revAuthor][1])

        return ret

    def GetGitCmd(self):
        "return the git cmd prefix as a list (for subprocess usage)"
        return self.git_cmd

    def GetAllCommits(self, since = None, limit = None):
        "return the revision list, since the commit 'since'. Optionally limit the number of commits"

        cmd = self.git_cmd + ['rev-list', '--reverse', '--topo-order', 'HEAD']
        if since:
            cmd = cmd + ['^' + since]
        if limit:
            cmd = cmd + ['-n', '%d' % limit]
        revs = subprocess.check_output(cmd).split('\n')

        # only return things long enough to be commits
        return [r for r in revs if len(r) > 8]


    def GetCommitProperties(self, rev):
        "returns a tuple of (timestamp, author name) for the given commit"
        
        cmd = self.git_cmd + ['log',
                              rev,
                              '-n', '1',
                              '--pretty=format:%at %aN']

        response = subprocess.check_output(cmd)
        spaceIdx = response.find(' ')
        if spaceIdx > 0:
            try:
                ts = int(response[:spaceIdx])
                author = response[spaceIdx+1:]
                return (ts, author)
            except ValueError:
                print "ERROR: could not convert log response '%s'" % response

        return (0, '')

        
