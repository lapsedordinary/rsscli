#!/usr/bin/python3
# https://github.com/lapsedordinary/rsscli/
import argparse
import sys
import os
import os.path
import sqlite3
import readchar 
import re
import requests
import feedparser
import urllib.parse
from bs4 import BeautifulSoup as bs4
import time
import datetime
import csv
import webbrowser
import threading
import logging
import pyperclip
from tendo import singleton

# setting the terminal width, default to 80 if it can't be set
termwidth = 80
try:
    termwidth = os.get_terminal_size().columns
except:
    termwidth = 80

configdir = os.path.expanduser('~/.rsscli/')
dbfile = configdir + 'database.db'

# checking the arguments
# this also serves as the help when the tool is invoked with the -h option
parser = argparse.ArgumentParser(description='''TODO''')
parser.add_argument('-a','--add',help='add one or more source URLs to the reader', metavar='URL', nargs='+')
parser.add_argument('-A','--addurl',help='bookmark and tag one or more URLs; you can use this to save URLs from external sources', metavar='URL', nargs='+')
parser.add_argument('--addcsv',help='add URLs to the reader from a CSV file with one URL per row and optionally the weight in the second column. This is useful when you want to import a lot of courses', metavar='file')
parser.add_argument('-b','--blackwhite',help='don\'t use terminal colours',default=0,metavar='',const='xxx',nargs='?')
parser.add_argument('-c','--recent',help='display items recently marked as read (default 10, but can be changed with -n)',default=0,const='xxx',nargs='?')
parser.add_argument('-C','--recentsaved',help='display items recently saved (default 10, but can be changed with -n)',default=0,const='xxx',nargs='?')
parser.add_argument('--checkfrequency',help='set the number of seconds before a feed is checked again (only makes sense when combined with -u)',default=900,metavar='seconds')
parser.add_argument('--delete',help='delete source URLs from the reader', metavar='URL',default='',nargs='+')
parser.add_argument('-e','--reverse',help='show items or sources in reverse',default=0,const='xxx',nargs='?')
parser.add_argument('-f','--find',help='find items exactly matching all tags',metavar='TAG',nargs='+')
parser.add_argument('-F','--force',help='run even when another instance is running', metavar='',default='',const='xxx',nargs='?')
parser.add_argument('-g','--renametag',help='rename a tag', metavar=('URL','name'),nargs=2)
parser.add_argument('--logfile',help='file to print logs to (by default logs are printed to standard output). Implies -b',default=0,metavar='',const='xxx',nargs='?')
parser.add_argument('-i','--min',help='minimum weight of sources to consider',default=1,metavar='weight')
parser.add_argument('-j','--adjustweight',help='adjust the weight of this source', metavar=('URL','weight'),nargs=2)
parser.add_argument('-l','--list',help='list all source URLs', metavar='',default='',const='xxx',nargs='?')
parser.add_argument('-m','--max',help='maximum weight of sources to consider',default=9,metavar='weight')
parser.add_argument('-n','--limit',help='limit the number of entries to display',default=0,metavar='number')
parser.add_argument('-o','--shortfind',help='when used with find, do not display tags and list date in short form first', metavar='',default=0,const='xxx',nargs='?')
parser.add_argument('-O','--orfind',help='when used with find, use OR rather than AND', metavar='',default=0,const='xxx',nargs='?')
parser.add_argument('-r','--renamefeed',help='rename this source', metavar=('URL','name'),nargs=2)
parser.add_argument('-s','--saved',help='show saved (bookmarked) items', metavar='',default='',const='xxx',nargs='?')
parser.add_argument('-S','--statistics',help='show usage statistics', metavar='',default='',const='xxx',nargs='?')
parser.add_argument('-t','--listtags',help='list all tags, can be limited by -n',default=0,metavar='',const='xxx',nargs='?')
parser.add_argument('--tempimport',help='add URLs to the reader from a CSV file; the second optional argument is the weight', metavar='file')
parser.add_argument('--threads',help='number of parallel threads when checking for updates',default=25,metavar='number')
parser.add_argument('-u','--update',help='read new entries from sources', metavar='',const='xxx',default='',nargs='?')
parser.add_argument('-U','--unread',help='mark entry as unread', metavar='URL', nargs='+')
parser.add_argument('-v','--verbose',help='print more verbose statements', metavar='',default=1,const='xxx',nargs='?')
parser.add_argument('-vv','--veryverbose',help='print even more verbose statements', metavar='',default=0,const='xxx',nargs='?')
parser.add_argument('-vvv','--veryveryverbose',help='print most verbose statements', metavar='',default=0,const='xxx',nargs='?')
parser.add_argument('-w','--website',help='create website with saved items',metavar='FILENAME',nargs='+')
parser.add_argument('-x','--copyurl',help='copy the url at the given line number, to combine with -z', metavar='number',default=1)
parser.add_argument('-z','--linenumber',help='print line numbers, to combine with -x', metavar='',default=0,const='xxx',nargs='?')
args = parser.parse_args()

linenumber = 0

# setting the loglevel
loglevel=logging.ERROR
if args.verbose: loglevel=logging.WARNING
if args.veryverbose: loglevel=logging.INFO
if args.veryveryverbose: loglevel=logging.DEBUG
logging.basicConfig(level=loglevel,filename=args.logfile,format='%(asctime)s %(levelname)s: %(message)s')

# We don't want to run multiple instances of the program in parallel, because this causes database lock issues
if not args.force:
    try:
        me = singleton.SingleInstance()
    except:
        quit()   

# 'saved' is a way to bookmark entries without marking them as read. They are essentially moved to a different 'queue'
saved = 0
if args.saved: saved = 1

blackwhite = args.blackwhite
if args.logfile: blackwhite = 1

sortorder = 'DESC'
if args.reverse: sortorder = 'ASC'

minweight = int(args.min)
maxweight = int(args.max)

shortfind = args.shortfind

limit = int(args.limit)

# it may be that some RSS feeds like to pretend we're a normal browser
feedparser.USER_AGENT = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:72.0) Gecko/20100101 Firefox/72.0"

# if the database doesn't exist, we need to create it
# this guides the user through that process
if not(os.path.isfile(dbfile)):
    myprint("No database file exists. I will create one in " + configdir + " which will be used in the future; is this okay? Type 'y' if it is and a database will be created, any other key will abort the program")
    yes = readchar.readchar()
    if yes.lower() != 'y':
        quit()
    if not(os.path.isdir(configdir)):
        os.mkdir(configdir)
    conn = sqlite3.connect(dbfile)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE source (url VARCHAR(1024) PRIMARY KEY NOT NULL, name VARCHAR(512), lastchecked INT DEFAULT 0, lastupdated INT DEFAULT 0, weight INT DEFAULT 5);''')
    cur.execute('''CREATE TABLE item (url VARCHAR(1024) PRIMARY KEY NOT NULL, source VARCHAR(1024) NOT NULL, time INT DEFAULT 0, readtime INT DEFAULT 0, addtime INT DEFAULT 0, title VARCHAR(300), author VARCHAR(256), description VARCHAR(4096) DEFAULT '', saved INT DEFAULT 0);''')
    cur.execute('''CREATE TABLE tag (tag VARCHAR(64) NOT NULL, url VARCHAR(1024) NOT NULL, FOREIGN KEY (url) REFERENCES item(url));''')
#    cur.execute('''CREATE TABLE entry (url VARCHAR(1024) PRIMARY KEY NOT NULL, timestamp INT DEFAULT 1, description VARCHAR(4096) DEFAULT "");''')
    quit("The database has now been initialised. You can now use the program to add URLs. Run\n\trsscli.pl -h\nfor help")

# we use global variables for the SQLite database connection and cursos
conn = sqlite3.connect(dbfile)
cur = conn.cursor()

# defining the colours (or not, if blackwhite is set)
def __red(text):
    return (text if blackwhite else '\033[31m' + text + '\033[0m')
def __blue(text):
    return (text if blackwhite else '\033[34m' + text + '\033[0m')
def __magenta(text):
    return (text if blackwhite else '\033[35m' + text + '\033[0m')
def __bold(text):
    return (text if blackwhite else '\u001b[1m' + text + '\033[0m')
def __underline(text):
    return (text if blackwhite else '\u001b[4m' + text + '\033[0m')

def ago(num):
    # rather than 3693 seconds ago, we say 1h1m33s ago etc.
    if num == 0:
        return 'never'
    if num < 60:
        return str(num) + 's ago'
    if num < 3600:
        minutes = int(num/60)
        seconds = num % 60
        return str(minutes) + 'm' + str(seconds) + 's ago'
    if num < 86400:
        hours = int(num/3600)
        num = num - 3600*hours
        minutes = int(num/60)
        seconds = num % 60
        return str(hours) + 'h' + str(minutes) + 'm' + str(seconds) + 's ago'
    days = int(num/86400)
    num = num - 86400*days
    hours = int(num/3600)
    num = num - 3600*hours
    minutes = int(num/60)
    seconds = num % 60
    return str(days) + 'd' + str(hours) + 'h' + str(minutes) + 'm' + str(seconds) + 's ago'

def myprint(text):
    # this allows us to print line numbers and, if needed, copy the URL in a specific line number
    global linenumber 
    linenumber = linenumber + 1
    if (args.linenumber):
        print( str(linenumber) + '. ' + text )
        if (int(args.copyurl) == linenumber):
            urls = re.findall('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),~#]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', text)
            if urls and urls[0]:
                if urls[0][-1:] == ')': urls[0] = urls[0][:-1]
                pyperclip.copy(urls[0])   
    else:
        print( text )

def findfeed(site):
    # a helper function that, given an HTTP URL, returns the URLs of the RSS feeds inside it
    raw = requests.get(site).text
    result = []
    possible_feeds = []
    html = bs4(raw,'lxml')
    feed_urls = html.findAll("link", rel="alternate")
    for f in feed_urls:
        t = f.get("type",None)
        if t:
            if "rss" in t or "xml" in t:
                href = f.get("href",None)
                if href:
                    possible_feeds.append(href)
    parsed_url = urllib.parse.urlparse(site)
    base = parsed_url.scheme+"://"+parsed_url.hostname
    atags = html.findAll("a")
    for a in atags:
        href = a.get("href",None)
        if href:
            if "xml" in href or "rss" in href or "feed" in href:
                possible_feeds.append(base+href)
    for url in list(set(possible_feeds)):
        f = feedparser.parse(url)
        if len(f.entries) > 0:
            if url not in result:
                result.append(url)
    return(result)

def addurltoreader(url,auto = 0, weight = 0):
    # adds a single source URL to the reader
    # if auto is set to 1, no userinterfaction is assumed and the URL is added with the weight given as an argument
    weight = int(weight)
    feed = feedparser.parse( url )
    if (feed['bozo']):
        logging.warning('%s is not a valid RSS feed; processing anyway' % __blue(url) )
#        return(0)
    title = ''
    if ( 'image' in feed['feed'] and 'title' in feed['feed']['image'] ):
        title = feed['feed']['image']['title']
    if ( 'title' in feed['feed'] ):
        title = feed['feed']['title']
    if not( title ):
        logging.warning('Can not find title for %s; set title to be the URL' % __blue(url) )
        title = url
#        return(0)
#    title = feed['feed']['title']
    if not(auto):
        myprint("Adding %s (%s).\nYou can give the feed a weight between 1 and 9 to indicate how interesting you find this source (9 = most interesting). If you enter anything but a number between 1 and 9, the default weight of 5 will be chosen" % ( __red(title), url ) )
        weight = readchar.readchar()
        if not(weight.isdigit()):
            weight = '0'
        weight = int(weight)
        if not(weight):
            weight = 5
    else:
        logging.info("Added %s (%s) to the feed" % ( __red(title), url ) )
    try:
        cur.execute('INSERT INTO source (url, name, weight) VALUES ( "%s" , "%s" , "%d" );' % ( url, title , weight) )
        conn.commit()
    except:
        if auto:
            logging.warning("Can't insert %s to reader; maybe it already exists?" % __blue(url) )
        else:
            myprint("Can't insert %s to reader; maybe it already exists?" % __blue(url) )
        return(0)
    return(1)

def addfromcsv(file):
    # expects a CSV file with two columns: a feed URL and, optionally, the weight
    # adds them automatically to the reader
    # (In the future, we may want to import from OPML)
    with open(file) as csvfile:
        reader = csv.reader(csvfile,delimiter=',')
        for row in reader:
            url = row[0]
            weight = 5
            if len(row) > 1: weight = row[1]
            addurltoreader(url,1,weight)
    return(1)
   
def listurls():
    # list all source URL and their name, weight and last update time
    cur.execute('SELECT * FROM source WHERE weight >= %d AND weight <= %d ORDER BY lastupdated %s' % ( minweight , maxweight , sortorder ));
    rows = cur.fetchall()
#    rows.sort(key=lambda x: x[1])
    now = int(time.time())
    for line in rows:
        myprint("%s (%s) Weight: %d; Last updated: %s" % (__red(line[1]) , line[0] , line[4], __blue(ago(now - line[3] if line[3] else 0) ) ) )

def listtags(limit):
    # list all tags, with the number of URLs tagged as such, ordered by this number. Optionally limits the number
    tags = {}
    cur.execute('SELECT * FROM tag')
    rows = cur.fetchall()
    for line in rows:
        tag = line[0]
        tags[tag] = 1 if not (tag in tags) else tags[tag]+1
    sortedtags = sorted(tags,key=lambda x: tags[x],reverse=(False if sortorder == 'ASC' else True))
    if limit:
        sortedtags = sortedtags[:limit]
    for t in sortedtags:
        myprint("%s: %d" % (t, tags[t] ))

def updateurl(url,name,lastchecked,lastupdated):
    # we need to reintialize conn and cur, because we'll operate inside a thread!
    origurl = url
    conn = sqlite3.connect(dbfile, timeout=15) # timeout added because the threads may block writing to database
    cur = conn.cursor()
    now = int(time.time())
#    newpid = os.fork()
#    if newpid: continue
    logging.info("Checking %s (%s) for updates (last checked %d seconds ago)" % ( __red(name),__blue(url),now - lastchecked))
    if lastchecked == 0 or (now - lastchecked) > int(args.checkfrequency):
        feed = {}
        status = 999
        c = 0 # counter
#        myprint("%s (%s): %d" % ( url, feed['href'], feed['status'] ) )
        try:
            while ( status != 200 and status != 404 and c < 10 ):
                feed = feedparser.parse( url )
                if 'status' in feed: status = feed['status']
                c = c + 1
                if 'href' in feed:
                    url = feed['href']
                else:
                    c = 10
                logging.debug('Status for %s is %d (%s)' % ( origurl, status, url ) )
            if status == 404: logging.warning('Status for %s is 404' % origurl )
            if status == 301: logging.warning('Status for %s is 301; redirect to %s' % ( origurl , url ) )
        except:
            logging.error("Something went wrong with %s (%d)" % ( origurl , status ) )
        try:
            cur.execute('UPDATE source SET lastchecked = %d WHERE url = "%s"' % ( now, origurl ) )
#            conn.commit()
        except sqlite3.Error as err:
            logging.error("Can't set last checked date for %s: %s" % (__blue(url), err.args[0]))
        if( 'bozo' in feed and feed['bozo'] ):
            logging.warning("Feed for %s (%s) is possibly invalid; proceeding anyway" % (__red(name),__blue(url)))
#            os._exit(0)
        updated = 0
        if 'entries' in feed.keys():
            # added 2020-02-07 
            # I only got this error when run remotely but just in case
            for e in feed['entries']:
                try:
                    # we can't be certain these arguments exist, so we need to check first
                    link = ''
                    if hasattr(e,'link'): link = e.link
                    author = ''
                    if hasattr(e,'author'): author = e.author
                    title = ''
                    if hasattr(e,'title'): title = e.title
                    title = title.replace('"','""')
                    summary = ''
                    if hasattr(e,'summary'): summary = e.summary
                    summary = summary.replace('"','""')
                    thetime = now
                    try:
                        if hasattr(e,'created_parsed'): thetime = time.mktime(e.created_parsed)
                    except:
                        logging.warning('Created time for %s cannot be parsed' % origurl )
                    try:
                        if hasattr(e,'published_parsed'): thetime = time.mktime(e.published_parsed)
                    except:
                        logging.warning('Published time for %s cannot be parsed' % origurl )
                    try:
                        if hasattr(e,'updated_parsed'): thetime = time.mktime(e.updated_parsed)
                    except:
                        logging.warning('Updated time for %s cannot be parsed' % origurl )
                    # we are using REPLACE here: things may have changed. It is obviously a bit slower though
                    # note that we do not remove links that have been removed from the feed, e.g. because the URL has been updated!
                    #cur.execute('INSERT INTO item (url, source, time, addtime, title, author, description, saved) VALUES ("%s", "%s", %d, %d, "%s", "%s", "%s" , %d) ON CONFLICT REPLACE INTO item ( time, addtime, title, author, description ) VALUES ( "%d" , "%d", "%s", "%s", "%s" ) WHERE url = "%s";' % (e.link , url , thetime , now , title, author, summary , 0 , thetime, now, title, author, summary, url ))
                    cur.execute('SELECT count(*) FROM item WHERE url = "%s"' % link )
                    if cur.fetchone()[0]:
                        cur.execute('UPDATE item SET title = "%s", author = "%s", description = "%s" WHERE url = "%s"' % (title, author, summary, link ) )
                    else:
                        cur.execute('INSERT INTO item (url, source, time, readtime, addtime, title, author, description, saved) VALUES ("%s", "%s", %d, %d, %d, "%s", "%s", "%s" , %d)' % (link , origurl , thetime , 0, now , title, author, summary , 0  ))
    #                conn.commit()
                    logging.info("%s (%s) added or updated" % (__red(title), __blue(link)))
                    updated = 1
                except sqlite3.Error as err:
                    logging.warning("Can't add item (%s) to database: %s" % (__blue(e.link), err.args[0]))
        if updated:
            try:
                cur.execute('UPDATE source SET lastupdated = %d WHERE url = "%s"' % ( now, origurl ) )
                conn.commit()
            except sqlite3.Error as err:
                logging.warning("Can't set last updated date for %s: %s" % (__blue(url), err.args[0]))
    else:
        logging.info("Checked %s too recently" % __red(name) )
    conn.commit()
#
def updateurls():
    cur.execute('SELECT * FROM source ORDER BY lastupdated ASC');
    for line in cur.fetchall():
#        url = line[0]
#        name = line[1]
#        lastchecked = line[2]
#        lastupdated = line[3]
#        updateurl(url,name,lastchecked,lastupdated)
        while 1: # turn into while 1 and remove previous five lines to enable parallel
            if (threading.active_count() < int(args.threads) + 1):
                url = line[0]
                name = line[1]
                lastchecked = line[2]
                lastupdated = line[3]
                t = threading.Thread(target=updateurl,args=(url,name,lastchecked,lastupdated))
                t.daemon = True
                t.start()
                break
            time.sleep(1)

def deleteurl(url):
    cur.execute('SELECT COUNT(*) FROM SOURCE WHERE url="%s";' % url)
    if (cur.fetchone()[0]):
        cur.execute('SELECT * FROM SOURCE WHERE url="%s";' % url)
        line = cur.fetchone()
        myprint("Are you sure you want to delete %s (%s) from the reader?" % ( __red(line[1]), __red(line[0]) ) )
        yes = readchar.readchar()
        if yes.lower() == 'y':
            try:
                cur.execute('DELETE FROM SOURCE WHERE url="%s";' % url);
                conn.commit()
                return(1)
            except:
                myprint("Can't delete %s from reader" % __blue(url) )
                return(0)
    else:
        myprint("Can't find %s in the reader; nothing to delete" % __blue(url))
        return(0)

def bookmark(url):
    cur.execute('SELECT tag FROM tag')
    conn.commit()
    tags = cur.fetchall()
    tagdict = {}
    for _tag in tags:
        tag = _tag[0]
        tagdict[tag] = 1 if not(tag in tagdict) else tagdict[tag]+1
    sortedtags = sorted(tagdict,key=lambda x: tagdict[x],reverse=True)
    done = 0
    thesetags = [ ]
    currenttag = ''
    while not(done) :
        predict = ''
        for t in sortedtags:
            if currenttag and t.find(currenttag) == 0:
                predict = t
                break
        # the next dozen lines or so are to print the tags and predictions as we type
        remaining = termwidth - 6 # for Tags:
        for t in thesetags:
            remaining = remaining - 1 - len(t)
        if predict:
            remaining = remaining - 1 - len(predict)
        else:
            remaining = remaining - 1 - len(currenttag)
        backspaces = remaining - len(currenttag) + len(predict)
        if not predict: backspaces = remaining
        sys.stdout.write( ('_' * backspaces ) + "\r" )
        sys.stdout.write( "\r" + __bold ('Tags: ')+ ' '.join(map(__magenta,thesetags)) + ( ' ' if len(thesetags) else '' ) + __underline(__magenta(currenttag)) + predict[len(currenttag):] + ( ' ' * remaining )  + ( "\b" * backspaces ) )
        sys.stdout.flush()
        key = readchar.readchar().lower()
#        myprint("KEY = " + str(ord(key[:1])) )
        if ( ord(key[:1]) >= 97 and ord(key[:1]) <= 122 ) or ( ord(key[:1]) >= 48 and ord(key[:1]) <= 57 ) or key == '-' or key == '&' or key == "'" or key == '.':
            currenttag = currenttag + key[:1]
        elif ord(key[:1]) == 127 and currenttag:
            currenttag = currenttag[:-1]
        elif ord(key[:1]) == 127 and not(currenttag) and len(thesetags):
            currenttag = thesetags.pop()
        elif key == ' '  and currenttag:
            thesetags.append(currenttag)
            currenttag = ''
        elif key == '\t' and predict:
            thesetags.append(predict)
            currenttag = ''
        elif key == '\r':
            if currenttag:
                thesetags.append(currenttag)
            try:
                cur.execute('DELETE FROM tag WHERE url = "%s"' % url )
                conn.commit()
            except:
                logging.warning('Failed to delete old tags for url %s' % url )
            for tag in thesetags:
                try:
                    cur.execute('INSERT INTO tag VALUES ("%s","%s")' % ( tag, url ) )
                    conn.commit()
                except:
                    logging.warning("Can't insert (\"%s\",\"%s\") into the database" % ( tag, url ) )
            done = 1
        if ord(key[:1]) == 27: #escape key
            return(0)
    return(len(thesetags))
    
def findtags(*tags):
    # find all the URLs mathings _all_ the tags
    cur.execute('SELECT * FROM tag')
    conn.commit
    urltags = cur.fetchall()
    urls = {}
    for ut in urltags:
        t = ut[0]
        u = ut[1]
        if not(u in urls): urls[u] = set()
        urls[u].add(t)
    foundurls = []
    for u in urls:
        if set(tags[0]).issubset(urls[u]):
            try:
                cur.execute('SELECT * FROM item WHERE url = "%s"' % u)
                conn.commit
                line = cur.fetchone()
                foundurls.append( { 'url' : u, 'time' : line[2] , 'title' : line[5], 'description': line[7] } )
            except:
                logging.warning('Something went wrong. Found tags for %s but this URL is not found in items' % u)
    sortedurls = sorted(foundurls,key=lambda x: x['time'],reverse=(False if sortorder == 'ASC' else True))
    count = 0
    for u in sortedurls:
        count = count+1
        if (limit > 0 and count > limit): break
        thesetags = []
        cur.execute('SELECT * FROM tag WHERE url = "%s"' % u['url'])
        conn.commit
        for l in cur.fetchall():
            thesetags.append(l[0])
        if shortfind:
            myprint("%s: %s" % ( __blue(datetime.datetime.fromtimestamp(u['time']).strftime("%B %d, %Y")),__bold(u['title'])) )
            myprint("%s" % u['url'])
        else:
            myprint("%s" % __bold(u['title']))
            myprint("%s\t%s" % ( __blue(time.ctime(u['time'])) , __magenta(' '.join(thesetags)) ))
            myprint("%s" % u['url'])
    return(1)

def findortags(*tags):
    # find all the URLs mathings at least one of the tags
    ortags = '" OR tag="'.join(list(tags[0]))
    cur.execute('SELECT * FROM tag WHERE tag="' + ortags + '"')
    conn.commit
    urltags = cur.fetchall()
    urls = {}
    for ut in urltags:
        t = ut[0]
        u = ut[1]
        if not(u in urls): urls[u] = set()
        urls[u].add(t)
    foundurls = []
    for u in urls:
#        if set(tags[0]).issubset(urls[u]):
            try:
                cur.execute('SELECT * FROM item WHERE url = "%s"' % u)
                conn.commit
                line = cur.fetchone()
                foundurls.append( { 'url' : u, 'time' : line[2] , 'title' : line[5], 'description': line[7] } )
            except:
                logging.warning('Something went wrong. Found tags for %s but this URL is not found in items' % u)
    sortedurls = sorted(foundurls,key=lambda x: x['time'],reverse=(False if sortorder == 'ASC' else True))
    count = 0
    for u in sortedurls:
        count = count+1
        if (limit > 0 and count > limit): break
        thesetags = []
        cur.execute('SELECT * FROM tag WHERE url = "%s"' % u['url'])
        conn.commit
        for l in cur.fetchall():
            thesetags.append(l[0])
        if shortfind:
            myprint("%s: %s" % ( __blue(datetime.datetime.fromtimestamp(u['time']).strftime("%B %d, %Y")),__bold(u['title'])) )
            myprint("%s" % u['url'])
        else:
            myprint("%s" % __bold(u['title']))
            myprint("%s\t%s" % ( __blue(time.ctime(u['time'])) , __magenta(' '.join(thesetags)) ))
            myprint("%s" % u['url'])
    return(1)

def renamefeed(url,name):
    # rename a feed
    try:
        cur.execute('UPDATE source SET name = "%s" WHERE url = "%s"' % ( name, url ) )
        conn.commit()
        logging.info('Updated %s to the new name %s' % ( __blue(url), __red(name)))
    except:
        logging.error('Couldn\'t update %s to the new name %s' % (__blue(url), __red(name)))
    quit()

def adjustweight(url,weight):
    # change the weight of a feed
    weight = int(weight)
    if weight < 1 or weight > 9:
        logging.error('Invalid weight; please choose a number between 1 and 9')
        quit()
    try:
        cur.execute('UPDATE source SET weight = %d WHERE url = "%s"' % ( weight , url ) )
        conn.commit()
        logging.info('Updated %s to the new weight %s' % ( __blue(url), __red(str(weight))))
    except:
        logging.error('Couldn\'t update %s to the new weight %s' % (__blue(url), __red(str(weight))))
    quit()

def renametags(old,new):
    # rename rags
    cur.execute('SELECT * FROM tag WHERE tag = "%s"' % new )
    if len(cur.fetchall()):
        myprint("Entries tagged as %s already exist. Are you sure you want to rename tags '%s' as '%s' too? You can't separate them afterwards!" % ( new, old, new ) )
        yes = readchar.readchar()
        if yes.lower() != 'y':
            quit()
    myprint('Okay then...')
    try:
        cur.execute('UPDATE tag SET tag = "%s" WHERE tag = "%s"' % ( new, old ))
        conn.commit()
    except:
        logging.error("Couldn't change the tag")
    quit()

def displayrecent(number):
    cur.execute('SELECT * FROM item ORDER BY readtime DESC LIMIT %d' % num )
    conn.commit()
    rows = cur.fetchall()
    for line in rows:
        url = line[0]
        source = line[1]
        title = line[5]
        author = line[6]
        if author: author = ' (' + author + ')'
        itemtime = time.ctime(line[2])
        sourcename = ''
        cur.execute( 'SELECT * FROM source WHERE url = "%s"' % source )
        one = cur.fetchone()
        if one:
            sourcename = __red(one[1]) + ' : '
        myprint('%s%s%s %s' % ( sourcename, __blue(title) , author, itemtime ) )
        myprint(url)
        tags = []
        cur.execute( 'SELECT * FROM tag WHERE url = "%s"' % url )
        r = cur.fetchall()
        for l in r:
            tags.append(l[0])
        if(len(tags)):
            myprint(__bold('Tags: ' ) + ' '.join(map(__magenta,tags)))
        myprint('')
    quit()

def displayrecentsaved(number):
    cur.execute('SELECT DISTINCT item.url,item.source,item.title,item.author,item.time FROM item,tag WHERE item.url = tag.url ORDER BY readtime DESC LIMIT %d' % num )
    conn.commit()
    rows = cur.fetchall()
    for line in rows:
        url = line[0]
        source = line[1]
        title = line[2]
        author = line[3]
        if author: author = ' (' + author + ')'
        itemtime = time.ctime(line[4])
        sourcename = ''
        cur.execute( 'SELECT * FROM source WHERE url = "%s"' % source )
        one = cur.fetchone()
        if one:
            sourcename = __red(one[1]) + ' : '
        myprint('%s%s%s %s' % ( sourcename, __blue(title) , author, itemtime ) )
        myprint(url)
        tags = []
        cur.execute( 'SELECT * FROM tag WHERE url = "%s"' % url )
        r = cur.fetchall()
        for l in r:
            tags.append(l[0])
        if(len(tags)):
            myprint(__bold('Tags: ' ) + ' '.join(map(__magenta,tags)))
        myprint('')
    quit()

def markunread(url):
    try:
        cur.execute('UPDATE item SET readtime = 0 WHERE url = "%s"' % url )
        conn.commit()
        logging.info('Marked %s as unread' % url )
    except sqlite3.Error as err:
        logging.error('Failed to mark %s as unread: %s' % ( url, err ) )

if (args.add):
    urls = args.add
    for url in urls:
        if not(re.match('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\), ]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',url)):
            myprint('Not a valid URL: %s"' % __blue(url))
            continue
        feed = feedparser.parse( url )
        if( ( not 'image' in feed['feed'] ) and ( not 'title' in feed['feed'] ) ):
            possfeeds = findfeed(url)
            if not(len(possfeeds)):
                myprint( "Sorry, %s is not a valid RSS feed and I can't find any valid feeds in the source either\nNote: this may be because the page redirects to a cookie page" % __blue(url))
                continue
            myprint("This is not a valid RSS feed, but I have found valid RSS feeds in here. Please enter the number of the feed you would like to add; any other key to quit")
            for i in range(0,len(possfeeds)):
                myprint("%d. %s" % (i+1, possfeeds[i] ))
            num = int(readchar.readchar())
            for i in range(0,len(possfeeds)):
                if num == i+1:
                    addurltoreader(possfeeds[i])
                    myprint("Added %s to the reader " % __blue(possfeeds[i]))
                    continue
#            myprint("No URL added")  
            continue
        if addurltoreader(url):
            myprint("Added %s to the reader " % __blue(url))
    quit()

if (args.addcsv):
    addfromcsv( args.addcsv )
    quit()
  
if (args.list):
    listurls()
    quit()

if (args.listtags):
    listtags(limit)
    quit()

if (args.update):
    updateurls()
    quit()

if (args.find and args.orfind):
    findortags(list(map(lambda x:x.lower(),args.find)))
    quit()

if (args.find):
    findtags(list(map(lambda x:x.lower(),args.find)))
    quit()

if (args.delete):
    for url in args.delete:
        if not(re.match('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\), ]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',url)):
            myprint('Not a valid URL: "%s"' % __blue(url))
            continue
        deleteurl(url)
    quit()

if (args.renamefeed):
    url = args.renamefeed[0]
    name = args.renamefeed[1]
    renamefeed(url,name)

if (args.adjustweight):
    url = args.adjustweight[0]
    weight = args.adjustweight[1]
    adjustweight(url,weight)

if (args.renametag):
    # rename rags
    old = args.renametag[0]
    new = args.renametag[1]
    renametags(old,new)

if (args.recent):
    num = int(args.limit)
    if num == 0: num = 10
    displayrecent(num)
    quit()

if (args.recentsaved):
    num = int(args.limit)
    if num == 0: num = 10
    displayrecentsaved(num)
    quit()

def gettitle(url):
    title = ''
    try:
        raw = requests.get(url).text
        html = bs4(raw,'lxml')
        if html.find("title"):
            title = html.find("title").string
    except:
        logging.warning('Cannot determine title for %s, asking manually' % url)
        title = input("Sorry, the title of this URL can't be determined, maybe it is down. Please enter it manually. If you don't enter anything, this URL won't be bookmarked: ")
    return (title)

def statistics():
    try:
        now = int(time.time())
        cur.execute('SELECT count(*) FROM item')
        numitems = cur.fetchone()[0]
        cur.execute('SELECT count(*) FROM tag')
        numtags = cur.fetchone()[0]
        cur.execute('SELECT count(DISTINCT tag) FROM tag')
        numuniqtags = cur.fetchone()[0]
        cur.execute('SELECT count(*) FROM source')
        numsources = cur.fetchone()[0]
        cur.execute('SELECT count(*) FROM source WHERE lastupdated > 0')
        numactivesources = cur.fetchone()[0]
        cur.execute('SELECT count(*) FROM source WHERE lastupdated > %d' % ( now - 3*24*3600 ))
        numrecentlyupdatedsurces = cur.fetchone()[0]
        print(
'''RSS READER usage statistics
%s items
%s tags (%s unique)
%s sources (%s active, %s updated in past three days)''' % ( numitems, numtags, numuniqtags, numsources, numactivesources, numrecentlyupdatedsurces) )
    except sqlite3.Error as err:
        logging.error("Error printing statistics: %s" % err )
     
# still broken
if (args.addurl):
    urls = args.addurl
    for url in urls:
        title = gettitle(url)
        if not title:
            continue
        if not bookmark(url):
            continue
        print("Bookmarked '%s' (%s)" % (title,url))
        now = int(time.time())
        try:
            cur.execute('DELETE FROM item WHERE url = "%s"' % url )
            cur.execute('INSERT INTO item ( url, source, title, time, addtime, readtime, saved ) VALUES ("%s", "", "%s", "%d", "%d", "%d", 0 ) ' % ( url, title, now, now, now ))
            conn.commit()
        except sqlite3.Error as err:
            logging.error('Cannot insert %s ("%s") into database: %s' % ( url, title , err ) )
        print()
    quit()

if (args.unread):
    for url in args.unread:
        markunread(url)
    quit()

if (args.statistics):
    statistics()
    quit()

##### TEMP #####
if (args.tempimport):
    dbfile2 = args.tempimport
    conn2 = sqlite3.connect(dbfile2)
    cur2 = conn2.cursor()
    cur2.execute("SELECT * FROM entry")
    rows = cur2.fetchall()
    for line in rows:
        url = line[0]
        source = ''
        time_ = line[1]
        readtime = 0
        addtime = int(time.time()) # now
        title = line[2]
        author = ''
        summary = ''
        saved = 0
        cur2.execute('SELECT * FROM read WHERE url = "%s"' % url )
        one = cur2.fetchone()
        if one:
            readtime = one[1]
            addtime = one[2]
            source = one[3]
            title = one[4]
        cur2.execute('SELECT * FROM tag WHERE url = "%s"' % url )
        r = cur2.fetchall()
        cur.execute('DELETE FROM tag WHERE url = "%s"' % url )
        for l in r:
            cur.execute('REPLACE INTO tag ( tag , url ) VALUES ( "%s", "%s" )' % ( l[0] , url ) )
        cur.execute('REPLACE INTO item (url, source, time, readtime, addtime, title, author, description, saved) VALUES ("%s", "%s", %d , %d, %d, "%s", "%s", "%s" , %d);' % ( url , source , time_ , readtime , addtime , title, author, summary , saved ))
        conn.commit()
        logging.info('Added "%s" (%s) to the new database' % ( __magenta( title ) , __blue( url ) ) )
    quit()
#### END TEMP ####

if (args.website):
    cur.execute( "SELECT * FROM item WHERE readtime = 0 AND saved = %d ORDER BY time %s" % ( saved , sortorder ) )
    rows = cur.fetchall()
    output = '''<html>
<head>
<title>RSSCLI output</title>
<meta charset="utf-8"/>
</head>
<style type="text/css">
h1 { font-size:20px; color:#101010; }
h1 a { color:#101010; font-decoration: none; }
h2 { font-size:15px; color:#101010; }
h3 { font-size:13px; color:#101010; }
h4 { font-size:12px; color:#101010; }
a { color:#800000; text-decoration: none; }
a:hover { background-color:#ffffc0; }
p.authortime { font-style: italic; font-size:10px; color:#000000; }
p.content { font-size:12px; }
</style>
<body>
'''
    for line in rows:
        url = line[0]
        itemtime = line[2]
        title = line[5]
        author = line[6]
        content = line[7]
        weight = 5
        source = line[1]
        cur.execute( 'SELECT * FROM source WHERE url = "%s"' % source )
        one = cur.fetchone()
        # this is when there is a matching source. There usually is, but maybe a source has since been deleted
        if one:
            weight = one[4]
            source = one[1]
        if weight < minweight: continue
        if weight > maxweight: continue
        output += ( '''<h1><a href="%s" target="_blank">%s : %s</a></h1>
<p class="authortime">%s, %s</p>
<p class="content">%s</p>
<hr />

''' % ( url, source, title, author, time.ctime(itemtime), content ) )
    output += '''</body>
</html>'''
    f = open(args.website[0],'w')
    f.write(output)
    quit()

    
# MAIN LOOP
# this runs when no other function is run
cur.execute( "SELECT * FROM item WHERE readtime = 0 AND saved = %d ORDER BY time %s" % ( saved , sortorder ) )
rows = cur.fetchall()
entries = []
for line in rows:
    url = line[0]
    itemtime = line[2]
    title = line[5]
    author = line[6]
    content = line[7]
    weight = 5
    source = line[1]
    cur.execute( 'SELECT * FROM source WHERE url = "%s"' % source )
    one = cur.fetchone()
    # this is when there is a matching source. There usually is, but maybe a source has since been deleted
    if one:
        weight = one[4]
        source = one[1]
    if weight < minweight: continue
    if weight > maxweight: continue
    # some HTML entities that don't print on the terminal
    # there will be many others, but these appear to be the most common
    content = re.sub('&#8211;','--',content)
    content = re.sub('&#8212;','---',content)
    content = re.sub('&#8216;',"'",content)
    content = re.sub('&#8217;',"'",content)
    content = re.sub('&#8220;','"',content)
    content = re.sub('&#8221;','"',content)
    content = re.sub('&#8230;','...',content)
    # next two lines remove HTML tags from the summary
    clean = re.compile('<.*?>') 
    content = re.sub(clean,'',content)
#    source = line[10]
#    if source : myprint("%s : %s (%s) %s; %d " % ( __red(source) ,__blue(__bold(title)), author , time.ctime(itemtime), weight))
    entries.append( { 'url' : url, 'itemtime' : itemtime, 'title' : title, 'author' : author, 'content' : content, 'weight' : weight, 'source' : source } )

myprint("%d entries" % len(entries))
counter = 0
while ( counter >= 0 and counter < len(entries) ):
    def printline(source,weight,title,author,itemtime):
        myprint("%s (%s): %s%s %s " % ( __red(source) , __magenta(str(weight)),__blue(__bold(title)), author , time.ctime(itemtime)))
    url = entries[counter]['url']
    itemtime = entries[counter]['itemtime']
    title = entries[counter]['title']
    author = entries[counter]['author']
    if author: author = ' (' + author + ')'
    content = entries[counter]['content']
    weight = entries[counter]['weight']
    source = entries[counter]['source']
    notnext = 1
    printline(source,weight,title,author,itemtime)
    while (notnext):
        key = readchar.readchar().lower()
        if key == '?' or key == 'h':
            myprint(  "\nThe following options are available:\n" + __underline(__red('b')) + "ookmark URL (and implicitly mark as read)\n" + __underline(__red('o')) + "pen in browser\n" + __underline(__red('q'))+"uit\nmark as " + __underline(__red('r')) + "ead\n" + __underline(__red('s')) + "how details\nprint " + __underline(__red('u')) + "rl\nopen in " + __underline(__red('w')) + "3m (text browser)\n" + __underline(__red('!')) + ' save to "bookmarks"\nopen 1' + __underline(__red('0')) + " entries in browser\nopen " + __underline(__red('5')) + " entries in browser\n" )
            continue
        if key == 'b':
            if bookmark( url ):
                try:
                    cur.execute('UPDATE item SET readtime = %d WHERE url = "%s"' % ( int(time.time()) , url ) )
                    conn.commit()
                except:
                    logging.warning('Failed to mark %s as read' % url )
                myprint('')
                notnext = 0
                counter = counter + 1
            else:
                myprint('')
                printline(source,weight,title,author,itemtime)
            continue
        if key == '5':
            for c in range(5):
                webbrowser.open(url)
                time.sleep(.3)
                counter = counter + 1
                if counter >= len(entries): break
                url = entries[counter]['url']
                if c < 4: printline(entries[counter]['source'],entries[counter]['weight'],entries[counter]['title'],entries[counter]['author'],entries[counter]['itemtime'])
            notnext = 0
            continue
        if key == '0':
            for c in range(10):
                webbrowser.open(url)
                time.sleep(.3)
                counter = counter + 1
                if counter >= len(entries): break
                url = entries[counter]['url']
                if c < 9: printline(entries[counter]['source'],entries[counter]['weight'],entries[counter]['title'],entries[counter]['author'],entries[counter]['itemtime'])
            notnext = 0
            continue
        if key == 'o':
            webbrowser.open(url)
            continue
        if key == 'n':
            notnext = 0
            counter = counter + 1
            continue
        if key == 'p':
            try:
                try:
                    cur.execute('UPDATE item SET readtime = 0 WHERE url = "%s"' % url )
                    conn.commit()
                except:
                    logging.warning("Can't mark %s as unread" % url)
            except:
                logging.warning("Can't mark '%s' (%s) as unread" % ( title , url ) )
            notnext = 0
            counter = counter - 1
            continue
        if key == 'r':
            try:
                now = int(time.time())
                try:
                    cur.execute('UPDATE item SET readtime = %d WHERE url = "%s"' % ( now , url ) )
                    conn.commit()
                except:
                    logging.warning("Can't mark %s as read" % url)
            except:
                logging.warning("Can't mark '%s' (%s) as read" % ( title , url ) )
            notnext = 0
            counter = counter + 1
            continue
        if key == 'u':
            myprint(url)
            continue
        if key == 'q':
            quit()
        if key == 's':
            myprint("\n" + content + "\n")
            printline(source,weight,title,author,itemtime)
        if key == 'w':
            os.system('w3m %s' % url )
            continue
        if key == '!':
            try:
                cur.execute('UPDATE item SET saved = 1 WHERE url = "%s"' % url )
                conn.commit()
                notnext = 0
                counter = counter + 1
            except:
                logging.warning('Failed to mark %s as read' % url )
            continue

















