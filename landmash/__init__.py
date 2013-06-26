#!/usr/bin/python

import requests
import time
import os
from bs4 import BeautifulSoup
from flask import Flask, request, render_template

app = Flask(__name__)


@app.route("/")
def root():
    films = LandmarkProxy().get_current_films('6/11/2013')

    rt = RTProxy()
    imdb = IMDBProxy()

    for f in films:
        f.rt = rt.get_rating(f)
        f.imdb = imdb.get_rating(f)

    best = sorted(films, key=lambda x: sort_films(x), reverse=True)
    return render_template('index.html', films=best)


def sort_films(x):
    if x.imdb > 0:
        return (x.rt + x.imdb*10)/2
    else:
        return (x.rt + x.rt-20)/2


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


class Film:

    def __init__(self, title, landmark_link):
        self.title = title
        self.href = "http://www.landmarktheatres.com" + landmark_link

    def __str__(self):
        return self.title

    def __repr__(self):
        return self.__str__()


class LandmarkProxy:

    def __init__(
            self, lm_url="http://www.landmarktheatres.com/Market/MarketShowtimes.asp"):
        self.lm_url = lm_url

    def get_current_films(self, date, market='Philadelphia'):
        r = requests.post(
            self.lm_url,
            params={
                'market': market},
            data={
                'ddtshow': date})
        links = BeautifulSoup(r.text).find_all('a', href=True)
        return [Film(x.string, x['href']) for x in links if x['href'].startswith('/Films')]


class RTProxy:

    def __init__(
            self, rt_url="http://api.rottentomatoes.com/api/public/v1.0/movies.json"):
        self.rt_url = rt_url
        self.rt_api_key = os.environ.get('RT_API_KEY')

    @RateLimited(10)
    def get_rating(self, film):
        r = requests.get(
            self.rt_url,
            params={'q': film.title,
                    'apikey': self.rt_api_key}).json()
        sort = sorted(r['movies'], key=lambda x: int( x['year'] if x['year'] else 0), reverse=True)
        return sort[0]['ratings']['critics_score']


class IMDBProxy:

    def __init__(self):
        pass

    def get_rating(self, film):
        r = requests.get(
            "http://imdbapi.org",
            params={
                'q': film.title,
                'limit': 10}).json(
                )
        try:
            sort = sorted(r, key=lambda x: int(
                x['year'] if x['year'] else 0), reverse=True)
            return sort[0]['rating']
        except :

    @RateLimited(10)
    def imdbapi_org(self, film):
        r = requests.get(
            "http://imdbapi.org",
            params={
                'q': film.title,
                'limit': 10}).json(
                )
        try:
            sort = sorted(r, key=lambda x: int(
                x['year'] if x['year'] else 0), reverse=True)
            return sort[0]['rating']
        except :
            return 0.0

    def omdbapi_com(self, film):
        r = requests.get(
            "http://omdbapi.com",
            params={
                't': film.title,
            }).json()
        try:
            return float(r['imdbRating'])
        except:
            return 0.0

