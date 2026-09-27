import json
from os import environ
from time import sleep

from requests import Session, post


class ApiUrl:
    MI_SEN = 'https://api.pollresults.org/v1.0/politics/results/senate'
    MI_GOV = 'https://api.pollresults.org/v1.0/politics/results/governor'


class PartyInd:
    DEM = '🔵'
    REP = '🔴'
    OTH = '🟡'

    @classmethod
    def replace(cls, party: str) -> str:
        return dict(DEM=cls.DEM, REP=cls.REP).get(party, cls.OTH)

    @classmethod
    def add(cls, party: str) -> str:
        return cls.replace(party) + party


class Candidates:
    NAME_MAPPER = {
        'Mike Rogers': 'Rogers',
        'Abdul El-Sayed': 'El-Sayed',
        'John James': 'James',
        'Jocelyn Benson': 'Benson',
    }

    @classmethod
    def validate_full_name(cls, full_name: str) -> bool:
        return full_name in set(cls.NAME_MAPPER.keys())

    @classmethod
    def get_surname(cls, full_name: str) -> str:
        return cls.NAME_MAPPER[full_name]


class Pollercoaster:
    def __init__(self, session: Session, api_url: str) -> None:
        self._session = session
        self._api_url = api_url
        self._response = None
        self._data: dict = {}
        self._previous_data: dict = {}

    def run(self) -> None:
        self._make_request()
        self._process_response()
        self._read_previous_data()
        if self._has_change():
            self._save_current_data()
            self._save_text()
        return

    def _make_request(self) -> None:
        self._response = self._session.get(self._api_url, params=dict(state='MI', limit=5))
        return

    def _process_response(self) -> None:
        polls = self._response.json()['results']
        for poll in polls:
            self._data.update(_create_poll_data(poll))
        return

    def _has_change(self) -> bool:
        self._polls_to_notify = {}
        for poll_id, lines in self._data.items():
            if poll_id not in self._previous_data.keys():
                self._polls_to_notify.update({poll_id: lines})
        return len(self._polls_to_notify) > 0

    def _read_previous_data(self) -> None:
        self._previous_data = json.load(open(f'data/{self._label}.json', encoding='utf8'))
        return

    def _save_current_data(self) -> None:
        with open(f'data/{self._label}.json', 'w', encoding='utf8') as f:
            json.dump(self._data, f, indent=2)
        return

    def _save_text(self) -> None:
        with open('data/text.txt', 'a', encoding='utf8') as f:
            f.write(self._text + '\n\n')
        return

    @property
    def _text(self) -> str:
        return '\n\n'.join('\n'.join(i) for i in self._polls_to_notify.values())

    @property
    def _label(self) -> str:
        return self._api_url.rsplit('/', 1)[-1]


def _create_poll_data(poll: dict) -> dict:
    field_dates_line = ' - '.join((poll['startDate'][:-3], poll['endDate'][:-3]))
    lines = [
        *_create_pollster_and_sponsor_lines(poll),
        field_dates_line,
        *[_create_poll_question_description(question) for question in poll['questions']],
    ]
    return {poll['pollId']: lines}


def _create_poll_question_description(question: dict) -> str:
    sample_size = question['sampleSize']
    sample_line = f'{sample_size} {question['population'].upper()}'
    results_desc = _create_poll_results_description(question)
    return '\n'.join((sample_line, results_desc))


def _create_poll_results_description(question: dict) -> str:
    sections = []
    leader_text = _create_poll_leader_line(question)
    for answer in question['answers']:
        if Candidates.validate_full_name(answer['candidateName']):
            answer['partyInd'] = PartyInd.replace(answer['party'])
            answer['surname'] = Candidates.get_surname(answer['candidateName'])
            sections.append('{partyInd} {surname} {pct}%'.format(**answer))
    if sections:
        sections.append(leader_text)
    return '\n'.join(sections)


def _create_poll_leader_line(question: dict) -> str:
    dem_pct = 0
    rep_pct = 0
    dem_surname = ''
    rep_surname = ''

    for answer in question['answers']:
        if Candidates.validate_full_name(answer['candidateName']):
            if answer['party'] == 'DEM':
                dem_pct = answer['pct']
                dem_surname = Candidates.get_surname(answer['candidateName'])
            elif answer['party'] == 'REP':
                rep_pct = answer['pct']
                rep_surname = Candidates.get_surname(answer['candidateName'])
        if dem_pct and rep_pct:
            break

    dem_lead = dem_pct - rep_pct
    leader_party = 'DEM' if dem_lead > 0 else ('REP' if dem_lead < 0 else 'TIE')
    leader_surname = dem_surname if dem_lead > 0 else (rep_surname if dem_lead < 0 else 'TIE')
    return f'=> {PartyInd.replace(leader_party)} {leader_surname} +{abs(round(dem_lead))}'


def _create_pollster_and_sponsor_lines(poll: dict) -> list:
    sections = [poll['displayName']]
    if poll['sponsors']:
        sections.append('$ ' + poll['sponsors'])

    if poll['partisan']:
        sections.append(PartyInd.add(poll['partisan']) + '-aligned')
    if poll['internal']:
        sections.append(PartyInd.add(poll['internal']) + ' Internal')

    if poll['sponsorCandidate']:
        if poll['sponsorCandidateParty']:
            sections.append('$ ' + PartyInd.replace(poll['sponsorCandidateParty']) + ' ' + poll['sponsorCandidate'])
        else:
            sections.append('$ ' + poll['sponsorCandidate'])

    return sections


def _send_notification() -> None:
    if text := open('data/text.txt', encoding='utf8').read().strip():
        post(
            'https://ntfy.sh/pollercoaster-' + environ['NTFY_SECRET'],
            data=text.encode('utf-8'),
            headers={'Title': 'Poll Alert', 'Tags': 'loudspeaker'},
        )

        with open('data/text.txt', 'w', encoding='utf8') as f:
            f.write(text)
    return


def _check_for_polls() -> None:
    session = Session()

    mi_sen = Pollercoaster(session, ApiUrl.MI_SEN)
    mi_gov = Pollercoaster(session, ApiUrl.MI_GOV)

    mi_sen.run()
    sleep(2)
    mi_gov.run()

    session.close()
    return


def main() -> None:
    _check_for_polls()
    _send_notification()
    return


if __name__ == '__main__':
    main()
