import requests
import re
import time
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import psycopg2
import urlparse
import os

rollcall_regex = r"\/legislative\/LIS\/roll_call_lists\/roll_call_vote_cfm\.cfm\?congress=[0-9]+&session=[0-9]+&vote=[0-9]+"
vote_menu_regex = r"\/legislative\/LIS\/roll_call_lists\/vote_menu_[0-9]+_[0-9]+\.htm"
senator_info_url = "http://www.senate.gov/general/contact_information/senators_cfm.xml"


STATES = ['AK', 'AL', 'AR', 'AZ', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD', 'ME', 'MI', 'MN', 'MO', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH', 'NJ', 'NM', 'NV', 'NY', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VA', 'VT', 'WA', 'WI', 'WV', 'WY']

class RequestFailedException(Exception):
    pass

class RollCall(object):
    url_regex = re.compile(".*/legislative\/LIS\/roll_call_lists\/roll_call_vote_cfm\.cfm\?congress=([0-9]+)&session=([0-9]+)&vote=([0-9]+)")

    @staticmethod
    def extract_rollcall_from_url(url):
        (congress_num, session_num, vote_num) = RollCall.url_regex.match(url).groups()
        return (congress_num, session_num, vote_num)

    @staticmethod
    def rollcall_to_id(congress_num, session_num, vote_num):
        return "%d-%d-%d" % (int(congress_num), int(session_num), int(vote_num))

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
        self.id = RollCall.rollcall_to_id(d["congress"], d["session"], d["vote_number"])

class Vote(object):
    def __init__(self, d):
        self.last_name = d["last_name"]
        self.first_name = d["first_name"]
        self.party = d["party"]
        self.state = d["state"]
        if d["vote_cast"] == "Yea":
            vote = 0
        elif d["vote_cast"] == "Nay":
            vote = 1
        else:
            vote = 2
        self.vote_cast = vote
        self.lis_member_id = d["lis_member_id"]

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

def init_database(conn):
    print "Initializing Database"
    cursor = conn.cursor()
    cursor.execute('''DROP TABLE IF EXISTS senator''')
    cursor.execute('''DROP TABLE IF EXISTS rollcall''')
    cursor.execute('''DROP TABLE IF EXISTS log''')
    columns = ["id varchar(20) PRIMARY KEY",
               "url text",
               "congress integer",
               "session integer",
               "congress_year integer",
               "vote_number integer",
               "vote_date timestamp",
               "vote_title text",
               "vote_document_text text",
               "majority_requirement varchar(10)",
               "vote_result text",
               "count_yea integer",
               "count_nay integer",
               "count_abstain integer DEFAULT 0",
               "tie_breaker_whom text",
               "tie_breaker_vote text"]
    for state in STATES:
        for senator in [0,1]:
            columns.append("%s%d integer NOT NULL" % (state, senator))
    for party in ["D", "R", "I"]:
            for vote in ["yea","nay","abstain"]:
                columns.append("total_%s_%s integer DEFAULT 0" % (party, vote))
    column_sql = ",".join(columns)
    cursor.execute('''CREATE TABLE rollcall (%s);''' % column_sql)
    # create a table for all the senators
    cursor.execute('''CREATE TABLE senator
        (first_name varchar(30),
         last_name varchar(30),
         party varchar(10),
         state varchar(10),
         address text,
         phone varchar(20),
         email text,
         website text,
         bioguide_id varchar(10),
         column_designation varchar(5)
        );''')
    # fetch all senator information
    print "Fetching senator information..."
    r = try_get_request(senator_info_url)
    root = ET.fromstring(r.text.encode('utf-8'))
    senators = []
    designation_counter = dict.fromkeys(STATES, 0)
    for element in root:
        if element.tag == "member":
            senator = extract_from_xml(element, 
                ["first_name", "last_name", "party", "state", "address",
                 "phone", "email", "website", "bioguide_id"])
            designation = designation_counter[senator["state"]]
            senator["column_designation"] = "%s%d" % (senator["state"], designation)
            designation_counter[senator["state"]] += 1
            senators.append(senator)
    print "Found %d/100 senators" % len(senators)
    senator_values = [(s["first_name"],
                       s["last_name"],
                       s["party"],
                       s["state"],
                       s["address"],
                       s["phone"],
                       s["email"],
                       s["website"],
                       s["bioguide_id"],
                       s["column_designation"]) for s in senators]
    cursor.executemany("INSERT INTO senator VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", senator_values)
    cursor.execute('''CREATE TABLE log (updated timestamp);''')
    conn.commit()

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
        vote_menu_regex)
    urls = list(set(urls))
    sub_urls = []
    for url in urls:
        new_urls = get_all_links_from_page(base_url + url, rollcall_regex)
        sub_urls += [base_url + new_url for new_url in new_urls]
    print "Found %d links in total" % len(sub_urls)
    return sorted(sub_urls)

def extract_from_xml(root, keys):
    result = dict.fromkeys(keys, "NULL")
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


def scrape(links):
    regex = re.compile(".*/legislative\/LIS\/roll_call_lists\/roll_call_vote_cfm\.cfm\?congress=([0-9]+)&session=([0-9]+)&vote=([0-9]+)")
    rollcalls = []
    for (i, link) in enumerate(links):
        (congress_num, session_num, vote_num) = regex.match(link).groups()
        print "Scraping %s-%s-%s (%d/%d)" % (congress_num, session_num, vote_num, i+1, len(links))
        xml_link = "https://www.senate.gov/legislative/LIS/roll_call_votes/vote%s%s/vote_%s_%s_%s.xml" % (congress_num, session_num, congress_num, session_num, vote_num)
        r = try_get_request(xml_link, n=100, wait=10)
        root = ET.fromstring(r.text.encode('utf-8'))
        # parse xml, extract roll call information
        rollcalls.append(parse_roll_call(link, root))
    return rollcalls

def populate_database(conn, rollcalls):
    cursor = conn.cursor()
    # load senator data from database, since we need to know the right column
    cursor.execute("SELECT last_name, state, column_designation FROM senator")
    senator_lookup = {(last_name, state):column_designation for (last_name, state, column_designation) in cursor.fetchall()}
    for rc in rollcalls:
        print "Populating database with id %s" % rc.id
        party_count = {"D":[0,0,0], "R":[0,0,0], "I":[0,0,0]}
        columns = ["id", "url", "congress", "session", "congress_year", "vote_number", "vote_date",
                   "vote_title", "vote_document_text", "majority_requirement", "vote_result",
                   "count_yea", "count_nay", "count_abstain", "tie_breaker_whom", "tie_breaker_vote"]
        values = [rc.id, rc.url, rc.congress, rc.session, rc.congress_year, rc.vote_number,
                  rc.vote_date, rc.vote_title, rc.vote_document_text, rc.majority_requirement,
                  rc.vote_result, rc.count["yeas"], rc.count["nays"], rc.count["absent"],
                  rc.tie_breaker["by_whom"], rc.tie_breaker["tie_breaker_vote"]]
        for v in rc.members:
            column_designation = senator_lookup[(v.last_name, v.state)]
            columns.append(column_designation)
            values.append(v.vote_cast)
            if v.party in party_count:
                party_count[v.party][v.vote_cast] += 1
            else:
                party_count["I"][v.vote_cast] += 1

        for party in ["D", "R", "I"]:
            for i, vote in enumerate(["yea","nay","abstain"]):
                columns.append("total_%s_%s" % (party, vote))
                values.append(party_count[party][i])

        column_sql = ",".join(columns)
        value_sql = ",".join(["%s"]*len(columns))
        cursor.execute('''INSERT INTO rollcall (%s) VALUES (%s);''' % (column_sql, value_sql), values)
        conn.commit()

def update_database(conn):
    cursor = conn.cursor()
    # get all the urls from the target url (115th congress first session)
    target_url = "https://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_115_1.htm"
    print "Updating database targeting %s" % target_url
    try:
        all_urls = get_all_links_from_page(target_url, rollcall_regex)
    except RequestFailedException as e:
        return { "new_rollcalls": 0, "status": RequestFailedException.message }
    ids = [RollCall.rollcall_to_id(*RollCall.extract_rollcall_from_url(url)) for url in all_urls]
    new_urls = []
    for (i, url) in zip(ids, all_urls):
        # check if rollcall exists or not
        cursor.execute("SELECT 1 FROM rollcall WHERE id=%s", (i,))
        exists = cursor.fetchone()
        if not(exists):
            new_urls.append("https://www.senate.gov" + url)
    print "Found %d new rollcalls to populate" % len(new_urls)
    # scrape all the new urls and populate database with them
    try:
        rollcalls = scrape(new_urls)
    except RequestFailedException as e:
        return { "new_rollcalls": 0, "status": RequestFailedException.message }
    populate_database(conn, rollcalls)
    # update the last updated time
    cursor.execute('''DELETE FROM log; INSERT INTO log (updated) VALUES (NOW() AT TIME ZONE 'EST');''')
    conn.commit()
    return { "new_rollcalls": len(rollcalls), "status": "success" }

def update_snitch(diagnostics):
    message = str(diagnostics)
    requests.post("https://nosnch.in/759e262024", data = { "m" : message })

# updates database with new rollcalls
def scrape_main(init=False):
    urlparse.uses_netloc.append("postgres")
    url = urlparse.urlparse(os.environ.get("DATABASE_URL", "postgresql://postgres:password@localhost/svh"))

    conn = psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )
    
    # Drop all tables and start from fresh
    if (init):
        init_database(conn)
    diagnostics = update_database(conn)
    update_snitch(diagnostics)

scrape_main()