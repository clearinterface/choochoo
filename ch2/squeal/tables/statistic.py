
import datetime as dt
from enum import IntEnum

from sqlalchemy import Column, Integer, ForeignKey, Text, UniqueConstraint, Float
from sqlalchemy.orm import relationship, backref

from .source import Source, Interval
from ..support import Base
from ..types import Owner
from ...lib.date import format_seconds, local_date_to_time


class StatisticName(Base):

    __tablename__ = 'statistic_name'

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)  # simple, displayable name
    description = Column(Text)
    units = Column(Text)
    summary = Column(Text)  # '[max]', '[min]' etc - can be multiple values but each in square brackets
    # we need to disambiguate statistics with the same name.
    # this is done by (1) "owner" (typically the source of the data) and
    # (2) by some additional (optional) constraint used by the owner (typically)
    # (eg activity_group.id so that the same statistic can be used across different activities)
    owner = Column(Owner, nullable=False)
    constraint = Column(Integer)
    UniqueConstraint(name, owner, constraint)

    def __str__(self):
        return 'StatisticName "%s"' % self.name


class StatisticJournalType(IntEnum):

    STATISTIC = 0
    INTEGER = 1
    FLOAT = 2
    TEXT = 3


class StatisticJournal(Base):

    __tablename__ = 'statistic_journal'

    id = Column(Integer, primary_key=True)
    type = Column(Integer, nullable=False)
    statistic_name_id = Column(Integer, ForeignKey('statistic_name.id', ondelete='cascade'), nullable=False)
    statistic_name = relationship('StatisticName')
    source_id = Column(Integer, ForeignKey('source.id', ondelete='cascade'), nullable=False)
    source = relationship('Source')
    # this is just for finding bugs
    # in fact (statistic_id, time) should be unique but that's across inheritance tables
    # the source_id field is only for delete on cascade. it's not an 'owner' as for statistics
    UniqueConstraint(statistic_name_id, source_id)

    __mapper_args__ = {
        'polymorphic_identity': StatisticJournalType.STATISTIC,
        'polymorphic_on': 'type'
    }

    def __str__(self):
        try:
            return 'StatisticJournal "%s"' % self.value
        except AttributeError:
            return 'Field Journal'

    @property
    def time(self):
        return self.source.time

    @classmethod
    def add(cls, log, s, name, units, summary, owner, constraint, source, value, type):
        statistic_name = s.query(StatisticName). \
            filter(StatisticName.name == name,
                   StatisticName.owner == owner,
                   StatisticName.constraint == constraint).one_or_none()
        if not statistic_name:
            statistic_name = StatisticName(name=name, units=units, summary=summary, owner=owner, constraint=constraint)
            s.add(statistic_name)
        else:
            if statistic_name.units != units:
                log.warn('Changing units on %s (%s -> %s)' % (statistic_name.name, statistic_name.units, units))
                statistic_name.units = units
            if statistic_name.summary != summary:
                log.warn('Changing summary on %s (%s -> %s)' % (statistic_name.name, statistic_name.summary, summary))
                statistic_name.summary = summary
        journal = s.query(StatisticJournal).join(Source). \
            filter(StatisticJournal.statistic_name == statistic_name,
                   Source.time == source.time).one_or_none()
        if not journal:
            journal = STATISTIC_JOURNAL_CLASSES[type](
                statistic_name=statistic_name, source=source, value=value)
            s.add(journal)
        else:
            if journal.type != type:
                raise Exception('Inconsistent StatisticJournal type (%d != %d)' %
                                (journal.type, journal))
            journal.value = value
        return journal

    def formatted(self):
        if self.value is None:
            return None
        units = self.statistic_name.units
        if not units:
            return '%d' % self.value
        elif units == 'm':
            if self.value > 2000:
                return '%dkm' % (self.value / 1000)
            else:
                return '%dm' % self.value
        elif units == 's':
            return format_seconds(self.value)
        elif units == 'km/h':
            return '%dkm/h' % self.value
        elif units == '%':
            return '%d%%' % self.value
        elif units == 'bpm':
            return '%dbpm' % self.value
        else:
            return '%d%s' % (self.value, units)

    @classmethod
    def at_date(cls, s, date, name, owner, constraint):
        start = local_date_to_time(date)
        finish = start + dt.timedelta(days=1)
        return s.query(StatisticJournal).join(StatisticName, Source). \
            filter(StatisticName.name == name,
                   Source.time >= start,
                   Source.time < finish,
                   StatisticName.owner == owner,
                   StatisticName.constraint == constraint).one_or_none()

    @classmethod
    def at_time(cls, s, time, name, owner, constraint):
        return s.query(StatisticJournal).join(StatisticName, Source). \
            filter(StatisticName.name == name,
                   Source.time == time,
                   StatisticName.owner == owner,
                   StatisticName.constraint == constraint).one_or_none()

    @classmethod
    def at_interval(cls, s, start, schedule, statistic_owner, statistic_constraint, interval_owner):
        return s.query(StatisticJournal).join(StatisticName, Interval). \
                    filter(StatisticJournal.statistic_name_id == StatisticName.id,
                           Interval.schedule == schedule,
                           Interval.start == start,
                           Interval.owner == interval_owner,
                           StatisticName.owner == statistic_owner,
                           StatisticName.constraint == statistic_constraint).all()


class StatisticJournalInteger(StatisticJournal):

    __tablename__ = 'statistic_journal_integer'

    id = Column(Integer, ForeignKey('statistic_journal.id', ondelete='cascade'), primary_key=True)
    value = Column(Integer)

    parse = int

    __mapper_args__ = {
        'polymorphic_identity': StatisticJournalType.INTEGER
    }

    @classmethod
    def add(cls, log, s, name, units, summary, owner, constraint, source, value):
        return super().add(log, s, name, units, summary, owner, constraint, source, value, StatisticJournalType.INTEGER)


class StatisticJournalFloat(StatisticJournal):

    __tablename__ = 'statistic_journal_float'

    id = Column(Integer, ForeignKey('statistic_journal.id', ondelete='cascade'), primary_key=True)
    value = Column(Float)

    parse = float

    @classmethod
    def add(cls, log, s, name, units, summary, owner, constraint, source, value):
        return super().add(log, s, name, units, summary, owner, constraint, source, value, StatisticJournalType.FLOAT)

    __mapper_args__ = {
        'polymorphic_identity': StatisticJournalType.FLOAT
    }

    def formatted(self):
        if self.value is None:
            return None
        units = self.statistic_name.units
        if not units:
            return '%f' % self.value
        elif units == 'm':
            if self.value > 2000:
                return '%.1fkm' % (self.value / 1000)
            else:
                return '%dm' % int(self.value)
        elif units == 's':
            return format_seconds(self.value)
        elif units == 'km/h':
            return '%.1fkm/h' % self.value
        elif units == '%':
            return '%.1f%%' % self.value
        elif units == 'bpm':
            return '%dbpm' % int(self.value)
        else:
            return '%s%s' % (self.value, units)


class StatisticJournalText(StatisticJournal):

    __tablename__ = 'statistic_journal_text'

    id = Column(Integer, ForeignKey('statistic_journal.id', ondelete='cascade'), primary_key=True)
    value = Column(Text)

    parse = str

    @classmethod
    def add(cls, log, s, name, units, summary, owner, constraint, source, value):
        return super().add(log, s, name, units, summary, owner, constraint, source, value, StatisticJournalType.TEXT)

    __mapper_args__ = {
        'polymorphic_identity': StatisticJournalType.TEXT
    }

    def formatted(self):
        if self.value is None:
            return None
        if not self.units:
            return '%s' % self.value
        else:
            return '%s%s' % (self.value, self.units)


class StatisticMeasure(Base):

    __tablename__ = 'statistic_measure'

    id = Column(Integer, primary_key=True)
    statistic_journal_id = Column(Integer, ForeignKey('statistic_journal.id', ondelete='cascade'), nullable=False)
    statistic_journal = relationship('StatisticJournal',
                                     backref=backref('measures', cascade='all, delete-orphan',
                                                     passive_deletes=True,
                                                     order_by='desc(StatisticMeasure.rank)'))
    source_id = Column(Integer, ForeignKey('source.id', ondelete='cascade'), nullable=False)  # must be an interval
    source = relationship('Source')
    rank = Column(Integer, nullable=False)  # 1 is best [1..n]
    percentile = Column(Float, nullable=False)  # 100 is best [0..100]
    quartile = Column(Integer)  # 0..4 at the min, 25%, median, 75% and max points


STATISTIC_JOURNAL_CLASSES = {
    StatisticJournalType.INTEGER: StatisticJournalInteger,
    StatisticJournalType.FLOAT: StatisticJournalFloat,
    StatisticJournalType.TEXT: StatisticJournalText
}


