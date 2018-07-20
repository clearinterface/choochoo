
import datetime as dt

from sqlalchemy import and_, or_
from urwid import Text, Padding, Pile, Columns, Divider, Edit, connect_signal, WEIGHT

from .log import make_log
from .repeating import DateOrdinals
from .squeal.binders import Binder
from .squeal.database import Database
from .squeal.diary import Diary
from .squeal.injury import Injury, InjuryDiary
from .squeal.schedule import ScheduleType, Schedule, ScheduleDiary
from .uweird.calendar import Calendar
from .uweird.decorators import Indent
from .uweird.factory import Factory
from .uweird.focus import FocusWrap, MessageBar
from .uweird.tabs import TabList
from .uweird.widgets import ColText, Rating, ColSpace, Integer, Float, DividedPile, DynamicContent
from .widgets import App


class InjuryWidget(FocusWrap):

    def __init__(self, tabs, bar, injury):
        factory = Factory(tabs, bar)
        self.pain_avg = factory(Rating(caption='average: '))
        self.pain_peak = factory(Rating(caption='peak: '))
        self.pain_freq = factory(Rating(caption='freq: '))
        self.notes = factory(Edit(caption='Notes: ', edit_text='', multiline=True))
        super().__init__(
            Pile([Columns([(WEIGHT, 1, Text(injury.title)),
                           (WEIGHT, 1, Columns([ColText('Pain - '),
                                                  (11, self.pain_avg),
                                                  (8, self.pain_peak),
                                                  (9, self.pain_freq),
                                                  ColSpace(),
                                                  ])),
                           ]),
                  self.notes,
                  ]))


class DynamicDate(DynamicContent):

    def __init__(self, log, session, bar, date):
        self.date = date
        super().__init__(log, session, bar)


class Injuries(DynamicDate):

    def _make(self):
        tabs = TabList()
        body = []
        for injury in self._session.query(Injury).filter(
                and_(or_(Injury.start == None, Injury.start <= self.date),
                     or_(Injury.finish == None, Injury.finish >= self.date))).\
                order_by(Injury.sort).all():
            widget = InjuryWidget(tabs, self._bar, injury)
            Binder(self._log, self._session, widget, InjuryDiary,
                   defaults={'injury_id': injury.id, 'date': self.date})
            body.append(widget)
        if body:
            return DividedPile([Text('Injuries'), Padding(DividedPile(body), left=2)]), tabs
        else:
            return Pile([]), tabs


class ScheduleWidget(FocusWrap):

    def __init__(self, log, tabs, bar, schedule):
        factory = Factory(tabs, bar)
        body = [Text('%s: %s' % (schedule.type.name, schedule.title))]
        if schedule.has_notes:
            self.notes = factory(Edit(caption='Notes: ', edit_text='', multiline=True))
            body.append(self.notes)
        super().__init__(Pile(body))


class Schedules(DynamicDate):

    def _make(self):
        ordinals = DateOrdinals(self.date)
        root_schedules = [schedule for schedule in
                          self._session.query(Schedule).filter(Schedule.parent_id == None).all()
                          if schedule.at_location(ordinals)]
        tabs = TabList()
        body = []
        for schedule in sorted(root_schedules):
            body.append(self.__make_schedule(tabs, ordinals, schedule))
        if body:
            return DividedPile([Text('Schedule'), Padding(DividedPile(body), left=2)]), tabs
        else:
            return Pile([]), tabs

    def __make_schedule(self, tabs, ordinals, schedule):
        widget = ScheduleWidget(self._log, tabs, self._bar, schedule)
        Binder(self._log, self._session, widget, table=ScheduleDiary,
               defaults={'date': ordinals.date, 'schedule_id': schedule.id})
        children = []
        for child in sorted(schedule.children):
            if child.at_location(ordinals):
                children.append(self.__make_schedule(tabs, ordinals, child))
        if children:
            widget = DividedPile([widget, Indent(DividedPile(children), width=2)])
        return widget


class DiaryApp(App):

    def __init__(self, log, session, bar, date=None):

        self.__session = session
        if not date: date = dt.date.today()
        factory = Factory(TabList(), bar)

        calendar = Calendar(log, bar, date)  # raw value needed below for signal
        self.date = factory(calendar)
        self.notes = factory(Edit(caption='Notes: ', multiline=True))
        self.rest_hr = factory(Integer(caption='Rest HR: ', maximum=100))
        self.sleep = factory(Float(caption='Sleep hrs: ', maximum=24, dp=1, units="hr"))
        self.mood = factory(Rating(caption='Mood: '), message='2: sad; 4: normal; 6 happy')
        self.weather = factory(Edit(caption='Weather: '))
        self.weight = factory(Float(caption='Weight: ', maximum=100, dp=1, units='kg'))
        self.medication = factory(Edit(caption='Meds: '))
        Binder(log, session, self, Diary, multirow=True, defaults={'date': date})
        connect_signal(calendar, 'change', self.date_change)

        self.injuries = factory.tabs.append(Injuries(log, session, bar, date=date))
        self.schedules = factory.tabs.append(Schedules(log, session, bar, date=date))

        body = [Columns([(20, Padding(self.date, width='clip')),
                         (WEIGHT, 1, Pile([self.notes,
                                           Divider(),
                                           Columns([self.rest_hr, self.sleep, self.mood]),
                                           Columns([(WEIGHT, 2, self.weather), (WEIGHT, 1, self.weight)]),
                                           self.medication,
                                           ]))],
                        dividechars=2),
                self.injuries,
                self.schedules,
                ]
        super().__init__(log, 'Diary', bar, DividedPile(body), factory.tabs, session)

    def date_change(self, unused_widget, date):
        self.__session.commit()
        self.injuries.rebuild(date)
        self.schedules.rebuild(date)
        self.root.discover()


def main(args):
    log = make_log(args)
    session = Database(args, log).session()
    DiaryApp(log, session, MessageBar()).run()
