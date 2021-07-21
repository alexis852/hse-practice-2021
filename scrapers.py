from bs4 import BeautifulSoup
import requests
import pandas as pd
from typing import Tuple, Dict, Set


class BadResponseError(Exception):
    """Класс исключения, которое предназначено для информирования о том,
    что попытка запроса через requests.get завершилась неудачно.
    """

    def __init__(self, response_code: int):
        """Задание кода, который был возвращен в результате запроса.

        :param response_code: код возврата (response.status_code)
        """
        self.response_code = response_code

    def __str__(self):
        return f'Bad response status code: {self.response_code}'


class BeautifulSoupHtmlParser:
    """Данный класс предназначен для парсинга веб-страницы с помощью BeautifulSoup."""

    OK_RESPONSE_STATUS = 200

    def __init__(self, parser: str):
        """Задание парсера, который будет использоваться
        (обычно html.parser или lxml|html5lib).

        :param parser: имя парсера
        """
        self.parser = parser

    def __call__(self, url: str) -> BeautifulSoup:
        """Парсинг html-кода веб-страницы по адресу url.

        :param url: целевая веб-страница
        :return: результирующий объект BeautifulSoup
        """
        response = requests.get(url)
        if response.status_code != BeautifulSoupHtmlParser.OK_RESPONSE_STATUS:
            raise BadResponseError(response.status_code)
        return BeautifulSoup(response.content, self.parser)


class HseEduProgramsWebScraper:
    """Класс, реализующий веб-скрапинг страницы с образовательными программами ВШЭ."""

    TARGET_TOWNS = ['Москва']
    REGULAR_DOMAINS = ['www.hse.ru']
    URL = 'https://www.hse.ru/education/msk/bachelor/'

    def __init__(self):
        self.faculties = {}  # Словарь факультет -> список всех ОП на нем
        self.programs = {}   # Словарь ОП -> код ОП
        self.loaded = False  # Были ли данные загружены ранее

    @staticmethod
    def sanitize_str(s: str) -> str:
        """Очистка строки от странных символов, которые могут быть в html-коде и от
        пробельных символов в начале и конце.

        :return: очищенная строка
        """
        return s.strip().replace('\xa0', ' ')

    def get(self) -> Tuple[Dict[str, Set[str]], Dict[str, str]]:
        """Получение и обработка данных с сайта Вышки со списком всех
        бакалаврских ОП Московского кампуса.

        :return: кортеж, первый элемент которого содержит информацию о факультетах и
        реализуемых на них ОП, а второй -- коды всех ОП.
        """
        if self.loaded:
            return self.faculties, self.programs

        parser = BeautifulSoupHtmlParser('html.parser')
        try:
            soup = parser(HseEduProgramsWebScraper.URL)
        except BadResponseError:
            raise
        programs_html = soup('div', id='education-programs__list')[0]
        for program in programs_html('div', 'edu-programm__item'):
            town, faculty = [self.sanitize_str(program('div', 'edu-programm__unit')[0]('span')[i].text) for i in [0, 1]]
            url = program.a['href'].split('/')
            if (town in HseEduProgramsWebScraper.TARGET_TOWNS) and ('ba' in url) and \
               (url[2] in HseEduProgramsWebScraper.REGULAR_DOMAINS):
                name = self.sanitize_str(program.a.text)
                code = url[-2]
                self.programs[name] = code
                if faculty not in self.faculties:
                    self.faculties[faculty] = set()
                self.faculties[faculty].add(name)

        # Из-за особенностей полученных данных, необходимо отождествить все пары факультетов,
        # название одного из которых является префиксом другого
        duplicates = []
        for faculty_i in self.faculties:
            for faculty_j in self.faculties:
                if faculty_i != faculty_j and faculty_i.find(faculty_j) != -1:
                    for program in self.faculties[faculty_i]:
                        self.faculties[faculty_j].add(program)
                    duplicates.append(faculty_i)
        for dup in duplicates:
            self.faculties.pop(dup)

        self.loaded = True
        return self.faculties, self.programs


class HseRatingGetter:
    """Класс, реализующий веб-скрапинг страниц с рейтингами."""

    def __init__(self, program: str, scraper: HseEduProgramsWebScraper):
        programs = scraper.get()[1]
        if program not in programs:
            raise ValueError('There is no such program in educational program list')
        self.url_code = programs[program]

    def __call__(self, rating_name: str, course: int) -> pd.DataFrame:
        """Получить датафрейм с рейтингом.

        :param rating_name: название рейтинга
        :param course: номер курса
        """
        parser = BeautifulSoupHtmlParser('html.parser')
        url = f'https://www.hse.ru/ba/{self.url_code}/ratings'
        try:
            soup = parser(url)
        except BadResponseError:
            raise
        url_from = None
        for option in soup('div', 'first_child last_child')[0]('select')[0]('option'):
            if option.text == rating_name:
                url_from = option['value']
                break
        else:
            raise ValueError('Irregular rating page or incorrect rating name')
        for option in soup('div', 'first_child last_child')[0]('select')[1]('option'):
            if course == int(option['value']):
                break
        else:
            raise ValueError('Incorrect course value')

        url = f'https://www.hse.ru/ba/{self.url_code}/ratings?from={url_from}&course={course}'
        try:
            soup = parser(url)
        except BadResponseError:
            raise
        names = []
        positions = []
        grade_mids = []
        grade_mins = []
        percentiles = []
        gpas = []
        for tr in soup('table')[0]('tr')[1:]:
            names.append(tr('td')[0].text)
            positions.append(tr('td')[1].text)
            if tr('td')[2].text != '':
                grade_mids.append(float(tr('td')[2].text))
            else:
                grade_mids.append(float('nan'))
            if tr('td')[3].text != '':
                grade_mins.append(int(tr('td')[3].text))
            else:
                grade_mins.append(float('nan'))
            percentiles.append(float(tr('td')[4].text[:-1]))
            gpas.append(float(tr('td')[5].text))

        res = pd.DataFrame(
            {
                'Студент': names,
                'Позиция в рейтинге': positions,
                'Средний балл': grade_mids,
                'Минимальный балл': grade_mins,
                'Перцентиль': percentiles,
                'GPA': gpas
            }
        )
        return res
