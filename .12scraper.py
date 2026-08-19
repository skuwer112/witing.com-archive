from urllib import request, parse
import json, re, os, mechanicalsoup
from datetime import datetime, timezone, timedelta
from defs import Chapter, StoryInfo, ServerRefusal
from dateutil import tz

import time

import lxml
from lxml import html

#logs in or reloads cookies upon import
from session import get_page, get_page_search
from session import browser

###   XPATHS AND REGEXPS   ###
#note that these return [] when a match fails

#For a chapter page
#   Really important note here. If the chapter's descent is '1' or '0' (it is the first chapter), you must format these chapter xpaths with '1'. else, format them with '0'.
#   This is because the first chapter doesn't have the additional div element before all content announcing which choice you just took.

chapter_title_xp                = "//span[starts-with(@title, 'Created')]/h2/text()"
chapter_content_xp              = "//div[@style='padding:25px 6px 20px 11px;min-width:482px;']/div"
chapter_author_name_xp          = "(//a[starts-with(@title, 'Username:')])[2]/text()"
chapter_author_name_xp_2        = '//i[starts-with(text(), "by")]/text()' #deleted authors?
chapter_author_link_xp          = '(//a[@class="imgLink imgPortLink"])[2]/@href' 
chapter_choices_xp              = "//div[@id='end_choices']/parent::*//a"
chapter_id_xp                   = '//*[text()="ID #"]/b/text()' #https://www.writing.com/main/interact/cid/#### it's a link on member accounts
chapter_created_date_xp         = "//span[starts-with(@title, 'Created')]/@title"

#For a story page
story_title_xp              =   "//a[contains(@class, 'proll')]/text()"
story_author_name_xp        =   "(//a[starts-with(@title, 'Username:')])[1]/text()"
story_author_link_xp        =   '(//a[@class="imgLink imgPortLink"])[1]/@href'
story_description_xp        =   "//*[@id='Content_Column_Inside']/div[6]/div[2]//td"
story_brief_description_xp  =   "//big/text()"
story_image_url_xp          =   "//meta[@property='og:image']/@content"
story_id_xp                 =   "//span[@class='selectAll']/text()"
story_rating_xp             =   '//div[starts-with(text(),"Rated: ")]/descendant-or-self::*/text()'
story_access_xp             =   '//div[starts-with(text(),"Access:")]/descendant-or-self::*/text()'
story_created_date          =   '//div[starts-with(text(),"Created")]/descendant-or-self::*/text()'
story_modified_date         =   '//div[starts-with(text(),"Modified")]/descendant-or-self::*/text()'
story_size                  =   '//div[starts-with(text(),"Size")]/descendant-or-self::*/text()'
story_keywords              =   '//meta[@name="keywords"]/@content'

recent_elements_xp          =   "//div[@class='mainLineBorderBottom'][@style='relative;padding:10px;']"
recent_date_xp              =   ".//div[@style='float:right;padding:0px 0px 0px 5px;']/text()"
recent_link_xp              =   ".//div[@align='left']/b/a/@href"

#For an outline
outline_chapters_xpath = "//*[@id='Content_Column_Inside']/div[6]/div[2]/pre//a"

redirect_links_xpath = "//a[starts-with(@href, 'https://www.Writing.Com/main/redirect')]"

#For the heavy server message
refusal_text_substring = b"or try again soon"

#A different error message that shows up once in a while
temporary_unavailable_substring = b"The site is temporarily unavailable."
temporary_unavailable2_substring = b"Database Temporarily Too Busy"
#A less nuclear option than above. Not sure if the UnicodeDecodeError was necessary

def hasServerRefusal(page):
    #Raw byte string check because some elements are not valid unicode
    check = html.tostring(page)

    if len(check) == 0:
        return True
    if refusal_text_substring in check:
        return True
    if temporary_unavailable_substring in check:
        return True
    if temporary_unavailable2_substring in check:
        return True
    return False

#Parse full date stamps like Created: February 30th, 2011 at 6:00am
#Used in details of the whole interactive
def parse_date_time(date):
    date = re.sub(r"(Modified:|Created:) ", "", date)
    date = re.sub(r"(st|nd|rd|th),", ",", date)
    timedate = datetime.strptime(date, "%B %d, %Y at %I:%M%p")

    timedate = timedate.replace(tzinfo=tz.gettz('America/New_York'))
    return int(timedate.timestamp())

#Parse shorthand dates like Oct 21, 2020 8:03 pm
def parse_short_date_time(date):
    timedate = datetime.strptime(date, "%b %d, %Y %I:%M %p")

    timedate = timedate.replace(tzinfo=tz.gettz('America/New_York'))
    return int(timedate.timestamp())

def parse_date(date):
    timedate = datetime.strptime(date, "Created: %m-%d-%Y")

    timedate = timedate.replace(tzinfo=tz.gettz('America/New_York'))
    return int(timedate.timestamp())

''' takes a link to a story landing page and returns a StoryInfo. '''
def get_story_info(story_id):
    url = "https://www.writing.com/main/interact/item_id/" + story_id
    page = get_page(url)
    
    while hasServerRefusal(page):
        page = get_page(url)

    #Private item can't access, can not scrape
    if page.text_content().lower().find('is a private item.') >= 0:
        return -1

    #Deleted item can't acccess, can not scrape
    if page.text_content().lower().find("wasn't found within writing.com") >= 0:
        return False

    #Not an interactive
    if page.text_content().lower().find("list_items/item_type/interactive-stories") == 0:
        return -2

    story_kw = page.xpath(story_keywords)
    if len(story_kw):
        story_kw = story_kw[0] # collapse xpath result to string
        story_kw = story_kw.split(",") # make into array of keywords
        story_kw = [kw.strip() for kw in story_kw] #Strip whitespaces

    access = None
    #Temporary registered users checker
    if page.text_content().lower().find("registered users and higher only") >= 0:
        access = True

    try:
        story_info = StoryInfo(
            id = int(page.xpath(story_id_xp)[0]),
            pretty_title = page.xpath(story_title_xp)[0],
            author_id = page.xpath(story_author_link_xp)[0][len("https://www.Writing.Com/main/portfolio/view/"):],
            author_name = page.xpath(story_author_name_xp)[0],
            description = html.tostring(page.xpath(story_description_xp)[0], encoding="unicode", with_tail=False),
            brief_description = page.xpath(story_brief_description_xp)[0],
            created = parse_date_time(page.xpath(story_created_date)[0] + page.xpath(story_created_date)[1]),
            modified = parse_date_time(page.xpath(story_modified_date)[0] + page.xpath(story_modified_date)[1]),
            image_url = page.xpath(story_image_url_xp)[0],
            rating = page.xpath(story_rating_xp)[1],
            last_full_update = None,
            keywords=story_kw,
            access = access
        )

    except Exception as e:
        raise e

    return story_info

def get_chapter(url):
    page = get_page(url)
    
    if hasServerRefusal(page):
        raise ServerRefusal('Heavy Server Volume')


    try:
        choices = []
        choice_elements = page.xpath(chapter_choices_xp)
        for choice in choice_elements:
            choices.append(choice.text_content())
        if len(choice_elements) == 0:
            choices = None

        if len(page.xpath(chapter_author_link_xp)) != 0:
            author_id = page.xpath(chapter_author_link_xp)[0][len("https://www.Writing.Com/main/portfolio/view/"):]
        else:
            author_id = None

        if len(page.xpath(chapter_author_name_xp)) != 0:
            author_name = page.xpath(chapter_author_name_xp)[0]
        else: 
            if len(page.xpath(chapter_author_name_xp_2)) != 0:
                author_name = page.xpath(chapter_author_name_xp_2)[0][3:].strip()

                if author_name == "":
                    author_name = None
            else:
                author_name = None

        if len(page.xpath(chapter_title_xp)) != 0:
            title = page.xpath(chapter_title_xp)[0]
        else:
            title = None

        if len(page.xpath(chapter_id_xp)) != 0:
            chapter_id = page.xpath(chapter_id_xp)[0]
        else:
            chapter_id = None

        chapter = Chapter(
            title = title,
            id = int(page.xpath(chapter_id_xp)[0]),
            content = html.tostring(page.xpath(chapter_content_xp)[0], encoding="unicode"),
            author_id = author_id,
            author_name = author_name,
            choices = choices,
            created = parse_date(page.xpath(chapter_created_date_xp)[0]),
            deleted = None
        )
    except Exception as e:
        print ("Scraping error at " + url)
        with open('scrapingerror.html','wb') as o:
            o.write(html.tostring(page))
        raise e

    return chapter

def get_recent_chapters(story_id):
    url = "https://www.writing.com/main/interactive-story/item_id/" + story_id + "/action/recent_chapters"
    page = get_page(url)
    
    while hasServerRefusal(page):
        page = get_page(url)


    output = {}
    recents = page.xpath(recent_elements_xp)

    url_cutoff = page.xpath(recent_link_xp)[0].rfind("/") + 1
    for recent in recents:
        #the descent
        link = recent.xpath(recent_link_xp)[0][url_cutoff:]
        date = parse_short_date_time(" ".join(recent.xpath(recent_date_xp)))
        output[link] = date
    
    return output

def get_outline(story_id):
    """Gets a list of all possible chapters for scraping"""
    url = "https://www.writing.com/main/interact/item_id/" + story_id + "/action/outline"
    page = get_page(url)
    
    while hasServerRefusal(page):
        page = get_page(url)

    descents = []
    outline_links = page.xpath(outline_chapters_xpath)

    #Pull the URL and find the last / to cut off the preceeding URL
    url_cutoff = outline_links[0].attrib['href'].rfind("/") + 1
    
    for a_element in outline_links:
        link = a_element.attrib['href'][url_cutoff:]
        descents.append(link)

    return descents


#TODO return dates too, so we can more easily get last modified dates to compare
def get_all_interactives_list(pages=-1, start_page=1, oldest_first=False, search_string=None):
    """
    Return interactive-story item IDs.

    The old implementation used /main/search.php. Writing.com now places
    a human-verification page in front of that endpoint for automated clients,
    so the old XPath sees zero results. For `run.py all`, use the logged-in
    user's portfolio instead, which exposes the user's interactive stories
    without the site-wide search challenge.

    `search_string` is retained for compatibility; when supplied, the old
    search endpoint is attempted first.
    """
    def extract_ids(page):
        ids = []
        seen = set()
        # Current Writing.com links use /main/interactive-story/item_id/<id>-<slug>
        # Older links may use /main/interact/item_id/<id>/...
        for href in page.xpath("//a/@href"):
            if not href:
                continue
            m = re.search(r"/main/(?:interactive-story|interact)/item_id/(\d+)", href)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                ids.append(m.group(1))
        return ids

    # If a search string was explicitly requested, keep supporting search URLs.
    if search_string is not None:
        search_url = "https://www.writing.com/main/search.php?"
        search_variables = {
            "action": "change_page",
            "ps_type": "5000",
            "ps": 1,
            "sort_by": "item_modified_time DESC",
            "sort_by_last": "item_modified_time DESC",
            "page": start_page,
            "search_for": search_string,
        }
        current_page = start_page
        interactives = []
        seen = set()

        while pages == -1 or (current_page - start_page) < pages:
            print("Getting search page " + str(current_page))
            search_variables["page"] = current_page
            url = search_url + parse.urlencode(search_variables)
            page = get_page_search(url)

            text = page.text_content().lower()
            if "verification required" in text or "confirm you are not a robot" in text:
                raise RuntimeError(
                    "Writing.com requires human verification on the search endpoint. "
                    "Open the search URL in a normal browser, complete verification, "
                    "then use `python run.py get <ID...>` for the desired stories."
                )

            ids = extract_ids(page)
            print("Znaleziono historii:", len(ids))
            if not ids:
                break
            for story_id in ids:
                if story_id not in seen:
                    seen.add(story_id)
                    interactives.append(story_id)
            current_page += 1

        return interactives

    # Default: archive all interactive stories in the logged-in user's portfolio.
    # This avoids the site-wide search anti-bot challenge.
    username = getattr(__import__("session"), "username", None)
    if not username:
        raise RuntimeError("Nie znaleziono username w konfiguracji.")

    url = "https://www.writing.com/main/portfolio/view/" + parse.quote(username)
    print("Pobieranie historii z portfolio użytkownika:", username)
    page = get_page_search(url)

    text = page.text_content().lower()
    if "verification required" in text or "confirm you are not a robot" in text:
        raise RuntimeError(
            "Writing.com wymaga weryfikacji również dla portfolio. "
            "Otwórz stronę portfolio w zwykłej przeglądarce i przejdź weryfikację."
        )

    interactives = extract_ids(page)

    # Try to follow a portfolio pagination link if one exists.
    # Stop on repeated pages or when `pages` is reached.
    seen = set(interactives)
    current = 1
    max_pages = pages if pages != -1 else 1000

    while current < max_pages:
        next_hrefs = page.xpath(
            "//a/@href"
        )
        next_url = None
        for href in next_hrefs:
            if not href:
                continue
            if re.search(r"/main/portfolio/view/" + re.escape(username) + r"/page/" + str(current + 1) + r"(?:$|[/?#])", href):
                next_url = href
                break
        if not next_url:
            break
        if next_url.startswith("/"):
            next_url = "https://www.writing.com" + next_url
        print("Pobieranie strony portfolio", current + 1)
        page = get_page_search(next_url)
        new_ids = extract_ids(page)
        before = len(interactives)
        for story_id in new_ids:
            if story_id not in seen:
                seen.add(story_id)
                interactives.append(story_id)
        if len(interactives) == before:
            break
        current += 1

    print("Łącznie znaleziono historii:", len(interactives))
    return interactives

