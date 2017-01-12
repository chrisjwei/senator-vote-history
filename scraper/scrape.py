import requests
import re
import time
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import pickle
import psycopg2
import urlparse
import os

class RequestFailedException(Exception):
    pass

class RollCall(object):
    {"congress", "session", "congress_year", "vote_number", "vote_date",
                      "vote_title", "vote_document_text", "majority_requirement", "vote_result",
                      "count", "tie_breaker", "members"}
    def __init__(self, url, d):
        self.url = url
        self.congress = int(d["congress"])
        self.session = int(d["session"])
        self.congress_year = int(d["congress_year"])
        self.vote_number = int(d["vote_number"])
        self.vote_date = d["vote_date"]
        self.vote_title = d["vote_title"]
        self.vote_document_text = d["vote_document_text"]
        self.majority_requirement = d["majority_requirement"]
        self.vote_result = d["vote_result"]
        self.count = d["count"]
        self.tie_breaker = d["tie_breaker"]
        self.members = d["members"]
        self.id = "%d-%d-%d" % (self.congress, self.session, self.vote_number)

class Vote(object):
    def __init__(self, d):
        self.last_name = d["last_name"]
        self.first_name = d["first_name"]
        self.party = d["party"]
        self.state = d["state"]
        self.vote_cast = d["vote_cast"]
        self.lis_member_id = d["lis_member_id"]

def init_database(conn):
    cursor = conn.cursor()
    cursor.execute('''DROP TABLE IF EXISTS vote''')
    cursor.execute('''DROP TABLE IF EXISTS rollcall''')
    cursor.execute('''CREATE TABLE rollcall 
        (id varchar(20) PRIMARY KEY,
         url text,
         congress integer,
         session integer,
         congress_year integer,
         vote_number integer,
         vote_date timestamp,
         vote_title text,
         vote_document_text text,
         majority_requirement varchar(10),
         vote_result text,
         count_yea integer,
         count_nay integer,
         count_abstain integer DEFAULT 0,
         tie_breaker_whom text,
         tie_breaker_vote text
         );
        ''')
    cursor.execute('''CREATE TABLE vote
        (rollcall_id varchar(20) references rollcall(id),
         first_name varchar(30),
         last_name varchar(30),
         party varchar(10),
         state varchar(10),
         vote_cast varchar(20),
         lis_member_id varchar(10)
        );''')
    conn.commit()

def try_get_request(url, n=1, wait=1, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36'}):
    for i in xrange(n):
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            return r
        if r.status_code == 404:
            break;
        print "(try %d/%d) Request failed for %s with status code %d... sleeping %ds" % (i+1, n, url, r.status_code, wait)
        time.sleep(wait)
    raise RequestFailedException(r.status_code)

def get_all_links_from_page(base_url, regex=".*"):
    r = try_get_request(base_url)
    if (r.status_code != 200):
        raise RequestFailedException(str(r.status_code))
    soup = BeautifulSoup(r.text, "html.parser")
    urls = []
    regex = re.compile(regex)
    for a in soup.find_all('a', href=True):
        link = a['href']
        if (regex.match(link)):
            urls.append(link)
    return urls

def scrape_init():
    '''
    Gets all the links to each individual vote and saves to a file
    '''
    base_url = 'https://www.senate.gov'
    urls = get_all_links_from_page(
        "https://www.senate.gov/pagelayout/legislative/a_three_sections_with_teasers/votes.htm",
        "\/legislative\/LIS\/roll_call_lists\/vote_menu_[0-9]+_[0-9]+\.htm")
    urls = list(set(urls))
    sub_urls = []
    for url in urls:
        new_urls = get_all_links_from_page(
            base_url + url,
            "\/legislative\/LIS\/roll_call_lists\/roll_call_vote_cfm\.cfm\?congress=[0-9]+&session=[0-9]+&vote=[0-9]+")
        sub_urls += [base_url + new_url for new_url in new_urls]
    print "Found %d links in total" % len(sub_urls)
    with open("links.txt", "w") as f:
        f.write("\n".join(sorted(sub_urls)))

def extract_from_xml(root, keys):
    result = dict.fromkeys(keys, None)
    for element in root:
        if (element.tag in result):
            result[element.tag] = element.text
    return result


def parse_roll_call(link, root):
    target_attribs = {"congress", "session", "congress_year", "vote_number", "vote_date",
                      "vote_title", "vote_document_text", "majority_requirement", "vote_result",
                      "count", "tie_breaker", "members"}
    attribs = dict.fromkeys(target_attribs, None)
    for child in root:
        if child.tag in target_attribs:
            if (len(child) == 0):
                attribs[child.tag] = child.text
            else:
                attribs[child.tag] = child
    # parse count
    attribs["count"] = extract_from_xml(attribs["count"], ["yeas", "nays", "absent"])
    # parse tie_breaker
    attribs["tie_breaker"] = extract_from_xml(attribs["tie_breaker"], ["by_whom", "tie_breaker_vote"])
    votes = []
    for member in attribs["members"]:
        vote_dict = extract_from_xml(member, ["last_name", "first_name", "party", "state", "vote_cast", "lis_member_id"])
        votes.append(Vote(vote_dict))
    attribs["members"] = votes

    return RollCall(link, attribs)


def scrape():
    regex = re.compile("https:\/\/www\.senate\.gov\/legislative\/LIS\/roll_call_lists\/roll_call_vote_cfm\.cfm\?congress=([0-9]+)&session=([0-9]+)&vote=([0-9]+)")
    rollcalls = []
    with open("links.txt", "r") as f:
        links = f.read().split("\n")
    for (i, link) in enumerate(links):
        (congress_num, session_num, vote_num) = regex.match(link).groups()
        print "Scraping %s-%s-%s (%d/%d)" % (congress_num, session_num, vote_num, i+1, len(links))
        xml_link = "https://www.senate.gov/legislative/LIS/roll_call_votes/vote%s%s/vote_%s_%s_%s.xml" % (congress_num, session_num, congress_num, session_num, vote_num)
        r = try_get_request(xml_link, n=100, wait=10)
        root = ET.fromstring(r.text)
        # parse xml, extract roll call information
        rollcalls.append(parse_roll_call(link, root))
    return rollcalls


def populate_database(conn):
    rollcalls = scrape()
    cursor = conn.cursor()
    for rc in rollcalls:
        # save rollcall to rollcall table
        cursor.execute('''INSERT INTO rollcall
            (id, url, congress, session, congress_year, vote_number, vote_date,
             vote_title, vote_document_text, majority_requirement, vote_result,
             count_yea, count_nay, count_abstain, tie_breaker_whom, tie_breaker_vote)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);''',
            (rc.id, rc.url, rc.congress, rc.session, rc.congress_year, rc.vote_number,
             rc.vote_date, rc.vote_title, rc.vote_document_text, rc.majority_requirement,
             rc.vote_result, rc.count["yeas"], rc.count["nays"], rc.count["absent"],
             rc.tie_breaker["by_whom"], rc.tie_breaker["tie_breaker_vote"]))
        for v in rc.members:
            cursor.execute('''INSERT INTO vote
                (rollcall_id, first_name, last_name, party, state, vote_cast, lis_member_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s);''',
                (rc.id, v.first_name, v.last_name, v.party, v.state, v.vote_cast, v.lis_member_id))
        conn.commit()

#urlparse.uses_netloc.append("postgres")
#url = urlparse.urlparse(os.environ["DATABASE_URL"])

conn = psycopg2.connect(
    database=url.path[1:],
    user=url.username,
    password=url.password,
    host=url.hostname,
    port=url.port
)
init_database(conn)
populate_database(conn)
