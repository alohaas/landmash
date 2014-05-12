#!/usr/bin/python

from datetime import datetime
from HTMLParser import HTMLParseError
import requests
import time
import os
import json
from bs4 import BeautifulSoup
from flask import Flask, request, render_template
from urlparse import urlparse
from pymongo import Connection

MONGO_URL = os.environ.get('MONGOHQ_URL')

if MONGO_URL:
    connection = Connection(MONGO_URL)
    db = connection[urlparse(MONGO_URL).path[1:]]
else:
    sys.exit("MongoDB URL not found, exiting")


app = Flask(__name__)


@app.route("/")
def root():
    try:
        d = datetime.today()
        date = "%d/%d/%d" % (d.month, d.day, d.year)
        landmark_films = LandmarkProxy().get_current_films(date)
        critics = [RTProxy(), IMDBProxy()]
        films = [Film(name, href, critics) for name, href in landmark_films]
        best = sorted(films, key=lambda x: sort_films(x), reverse=True)
        return render_template('index.html', films=enumerate(best), date=date)

    except StatusError:
        return "Landmark Website Down!"


def sort_films(x):
    return sum([e.normalized for e in x.reviews])/float(len(x.reviews))


def RateLimited(maxPerSecond):
    minInterval = 1.0 / float(maxPerSecond)

    def decorate(func):
        lastTimeCalled = [0.0]

        def rateLimitedFunction(*args, **kargs):
            elapsed = time.clock() - lastTimeCalled[0]
            leftToWait = minInterval - elapsed
            if leftToWait > 0:
                time.sleep(leftToWait)
            ret = func(*args, **kargs)
            lastTimeCalled[0] = time.clock()
            return ret
        return rateLimitedFunction
    return decorate


class StatusError(Exception):

    def __init__(self, status_code):
        self.status_code = status_code

    def __str__(self):
        return repr(self.status_code)


class Film:

    def __init__(self, title, landmark_link, critics):
        self.reviews = []
        self.title = title
        self.critics = critics
        self.href = "http://www.landmarktheatres.com" + landmark_link
        self.img = "http://www.landmarktheatres.com/Assets/Images/Films/%s.jpg" % (
            landmark_link.split("=")[1])
        for critic in critics:
            review = critic.get_review(self)
            self.reviews.append(review)

        self.add_to_db()

    def add_to_db(self):
        if db.films.find_one({"title": self.title}) is None:
            db.films.insert({
                "title": self.title,
                "href": self.href,
                "img": self.img
            })

    def __str__(self):
        return self.title

    def __repr__(self):
        return self.__str__()


class LandmarkProxy:

    def __init__(self):
        self.lm_url = "http://www.landmarktheatres.com/Market/MarketShowtimes.asp"

    def get_current_films(self, date, market='Philadelphia'):
        listing = db.listings.find_one({"date": date})

        if listing is None:
            films = self.make_request(date, market)
            db.listings.insert({
                "date": date,
                "markets": [
                    {
                        "market": market,
                        "films": [title for title, _ in films]
                    }
                ]
            })

            app.logger.debug(films)
            return films
        else:
            app.logger.debug(listing)
            films = self.make_request(date, market)  # temporary
            for f in films:
                app.logger.debug(json.dumps(f, default=lambda x: x.__dict__))
            return films

    def make_request(self, date, market):
        r = requests.post(
            self.lm_url,
            params={
                'market': market},
            data={
                'ddtshow': date})
        if r.status_code != 200:
            raise StatusError(r.status_code)
        links = BeautifulSoup(r.text).find_all('a', href=True)
        return [(x.string, x['href']) for x in links if x['href'].startswith('/Films')]


class Review():

    def __init__(self, critic_id, rating, url, normalized):
        self.critic_id = critic_id
        self.rating = rating
        self.url = url
        self.normalized = normalized


class Critic():

    def __init__(self, critic_id):
        self.critic_id = critic_id

    def get_review(self, film):
        raise NotImplementedError


class RTProxy(Critic):

    def __init__(self):
        Critic.__init__(self, "rotten_tomatoes")
        self.rt_url = "http://api.rottentomatoes.com/api/public/v1.0/movies.json"
        self.rt_api_key = os.environ.get('RT_API_KEY')

    @RateLimited(10)
    def get_review(self, film):
        r = requests.get(
            self.rt_url,
            params={'q': film.title,
                    'apikey': self.rt_api_key}).json()
        results = r['movies']

        if len(results):
            return Review(self.critic_id, results[0]['ratings']['critics_score'], results[0]['links']['alternate'], results[0]['ratings']['critics_score'])
        else:
            return None


class IMDBProxy(Critic):

    def __init__(self):
        Critic.__init__(self, "imbd")

    def run_search(self, film, exact=True):
        r = requests.get(
            "http://www.imdb.com/find",
            params={
                'q': film.title,
                's': 'tt',
                'ttype': 'ft',
                'exact': str(exact).lower()
            })
        parsed = False
        parsed_results = None
        text = r.text
        while(not parsed):
            parsed = True
            try:
                parsed_results = BeautifulSoup(text)
            except HTMLParseError as e:
                textlist = text.splitlines()
                del textlist[e.lineno - 1]
                text = '\n'.join(textlist)
                parsed = False
        results = parsed_results.find_all(
            'td',
            attrs={
            'class': 'result_text'})
        if len(results):
            return results
        else:
            return self.run_search(film, False)

    def get_review(self, film):
        results = self.run_search(film)
        if len(results):
            url = results[0].a['href'].split('?')[0]
            url = "http://www.imdb.com" + url
            r2 = requests.get(url)
            rating = BeautifulSoup(
                r2.text).find_all(
                    'div',
                    attrs={'class': 'titlePageSprite'})[0].text.strip()
            return Review(self.critic_id, float(rating), url, float(rating)*10)

        else:
            return None
