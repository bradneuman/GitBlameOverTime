#!/usr/bin/python

# Updates (or initializes) the database and fills it in with missing commits from git. Can be insanely slow
# the first time

# Requires sqlite3

import sqlite3
import subprocess

repo_path = "/Users/bneuman/Documents/code/das-tools"
#run git with -C reop_path --no-pager

git_cmd = ['git', '-C', repo_path, '--no-pager']

rev = "01c2d9c463d1ffee0a1fb6a9c379aa88f76db8f3"


def GetDiffStats(rev, debug = False):
    "return a tuple of 4 things:\n"
    "  * a dictionary of old filename -> list of tuple (lineNum, numberOfLines). These are the lines\n"
    "    in the old file that were deleted by this commit\n"
    "  * a dictionary of new filename -> number of lines added by the author\n"
    "  * a dictionary of new filename -> number of lines removed by the author (will be negative)\n"
    "  * a list of tuples of file renames (oldFilename, newFilename)"

    def dprint(s):
        if debug:
            print("    # %s\n" % s)


    # cmd = git_cmd + ['diff',
    #                  '-C', # find copies
    #                  '-M', # find moves
    #                  '-U0', # don't print extra lines around diff
    #                  '--no-color',
    #                  rev+'^', # diff between rev and what came before rev
    #                  rev
    #              ]

    cmd = git_cmd + ['show',
                     '-C', # find copies
                     '-M', # find moves
                     '-U0', # don't print extra lines around diff
                     '--no-color',
                     # rev+'^', # diff between rev and what came before rev
                     rev
                 ]

    oldLinesPerFile = {}
    numNewLinesPerFile = {} # key is new file
    numDeletedLinesPerFile = {} # key is new file
    renames = []

    state = -1
    state_diff_header = 1
    state_diff_body = 2

    oldFile = ''
    newFile = ''

    data = subprocess.check_output(cmd)
    for line in data.split('\n'):
        if debug:
            print line
        if len(line)>0:
            if line[:4] == "diff":
                oldFile = None
                newFile = None
                state = state_diff_header
                continue


            if state == state_diff_header:
                if line[:3] == '---':
                    if line[:14] != "--- /dev/null":
                        oldFile = line[6:]
                        dprint(" old file is %s" % oldFile)
                        continue
                elif line[:3] == '+++':
                    if line[:14] != "+++ /dev/null":
                        newFile = line[6:]
                        dprint(" new file is %s" % newFile)
                        # this comes second
                        if oldFile and oldFile != newFile:
                            renames.append( (oldFile, newFile) )
                        continue

                elif line[:2] == '@@':
                    state = state_diff_body

            if state == state_diff_body:
                
                if line[:2] == '@@':
                    # find ending @@
                    endIdx = line.find('@@', 3)
                    if endIdx > 2:
                        for lineChunk in line[3:endIdx-1].split(' '):
                            commaIdx = lineChunk.find(',')
                            if commaIdx >= 0:
                                try:
                                    newLineInfo = (int(lineChunk[1:commaIdx]), int(lineChunk[commaIdx+1:]))
                                except ValueError:
                                    dprint(" value error! couldn't parse!")
                                    break # for lineChunk
                            else:
                                try:
                                    # if there's one line, no comma is printed
                                    newLineInfo = (int(lineChunk[1:]), 1)
                                except ValueError:
                                    dprint(" value error! couldn't parse!")
                                    break # for lineChunk


                            if newLineInfo[1] > 0:
                                if lineChunk[0] == '-':
                                    if oldFile not in oldLinesPerFile:
                                        oldLinesPerFile[oldFile] = []
                                    oldLinesPerFile[oldFile].append(newLineInfo)
                                    dprint("oldLines")

                # these are at the bottom ebecause they could fuck up with '---' or '+++'
                elif line[0] == '+':
                    dprint("line added")
                    nc = 0
                    if newFile in numNewLinesPerFile:
                        nc = numNewLinesPerFile[newFile]
                    numNewLinesPerFile[newFile] = nc + 1
                elif line[0] == '-':
                    dprint("line removed")
                    dc = 0
                    if oldFile in numDeletedLinesPerFile:
                        dc = numDeletedLinesPerFile[oldFile]
                    numDeletedLinesPerFile[oldFile] = dc - 1

    return (oldLinesPerFile, numNewLinesPerFile, numDeletedLinesPerFile, renames)

def GetOldBlameStats(rev, oldLinesPerFile, debug = False):
    "Given a revision and some info on lines in the old file from diff stats,\n"
    "  return a dictionary of filename -> list of (author, lines lost) lines will be negative"
    def dprint(s):
        if debug:
            print("## %s\n" % s)

    blame_cmd = git_cmd + ['blame',
                           '-w', # ignore whitespace
                           '-C', # find copies
                           '-M', # find moves
                           '--line-porcelain' # print info for each line
                       ]

    linesLost = {}

    for filename in oldLinesPerFile:
        dprint("getting stats for '%s'" % filename)
        linesLost[filename] = []

        cmd = blame_cmd + \
              [ "-L %d,+%d"% (startLine, numLines) for startLine, numLines in oldLinesPerFile[filename]] + \
              [rev+"^", '--', filename]

        linesLostPerAuthor = {}

        dprint(" ".join(cmd))
        for line in subprocess.check_output(cmd).split('\n'):
            if line[:7] == "author ":
                author = line[7:]
                dprint("%s lost a line" % author)
                ac = 0
                if author in linesLostPerAuthor:
                    ac = linesLostPerAuthor[author]
                linesLostPerAuthor[author] = ac - 1

        for author in linesLostPerAuthor:
            linesLost[filename].append( (author, linesLostPerAuthor[author]) )

    return linesLost


def GetCommitStats(rev, debug = False):
    "take a given revision and return a dictionary of new filename -> lines added / lost"

    oldLinesPerFile, numNewLinesPerFile, numDeletedLinesPerFile, renames = GetDiffStats(rev, debug)

    # from pprint import pprint

    # pprint(oldLinesPerFile)
    # pprint(numNewLinesPerFile)
    # pprint(numDeletedLinesPerFile)
    # pprint(renames)

    linesLost = GetOldBlameStats(rev, oldLinesPerFile, debug)

    # pprint(linesLost)

    # do a few checks
    # filenames1 = set(numDeletedLinesPerFile.keys())
    # filenames2 = set(linesLost.keys())
    # if filenames1.difference(filenames2):
    #     print "ERROR: not all filenames present in blame and diff for commit '%s'" % rev
    #     return None

    for filename in numDeletedLinesPerFile:
        total1 = numDeletedLinesPerFile[filename]
        total2 = sum([num for auth,num in linesLost[filename]])
        if total1 != total2:
            print "ERROR: number of blame lines and deleted lines differs for commit '%s'" % rev

    cmd = git_cmd + ['log',
                     '-n', '1', # only show one enry
                     '--format=%aN', # just print author name
                     rev
                 ]
    revAuthor = subprocess.check_output(cmd)
    if revAuthor[-1] == '\n':
        revAuthor = revAuthor[:-1]

    # print "author of revision is '%s'" % revAuthor
            
    ret = linesLost

    # now add the lines added. We don't need to run blame for these becaue we know they'll be blamed on the
    # author of the revision
    for filename in numNewLinesPerFile:
        if filename not in ret: # will happen for new files
            ret[filename] = []
        ret[filename].append( (revAuthor, numNewLinesPerFile[filename]) )

    return ret

from pprint import pprint

pprint(GetCommitStats(rev))
        

# utility functions for dealing with multiple results
def CombineStats(lhs, rhs):
    "combine the two sets of commit stats, store into lhs"
    for filename in rhs:
        if filename not in lhs:
            lhs[filename] = []
        lhs[filename] = lhs[filename] + rhs[filename]

def SquashStats(stats):
    "combine authors with the same name, adding their lines. return new result"
    ret = {}

    for filename in stats:
        ret[filename] = []
        blameLines = {}
        for author, numLines in stats[filename]:
            nl = 0
            if author in blameLines:
                nl = blameLines[author]
            blameLines[author] = nl + numLines

        for author in blameLines:
            if blameLines[author] != 0:
                ret[filename].append( (author, blameLines[author]) )

    return ret

def blameTester():
    "simulates doing a git blame on all current files, but using the commit by commit"
    "machinery here"


    # just for testing, lets try coming up with the ending blame stats
    cmd = git_cmd + ['rev-list', 'HEAD', '--reverse']
    revs = subprocess.check_output(cmd).split('\n')

    total = {}

    for rev in revs:
        if len(rev) > 8: # sha-1s should be long
            print rev
            stats = GetCommitStats(rev)
            CombineStats(total, stats)
            total = SquashStats(total)

    # remove empty entries (e.g. files that are deleted)
    total = {k: v for k,v in total.items() if v}

    return total

pprint(blameTester())
