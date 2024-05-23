import re
import time
import requests
from aqt import mw, gui_hooks
from aqt.utils import showInfo, qconnect
from aqt.qt import *

#Assume that I just use one of the selected problems/scenarios for first review

#get all cards requiring generation and process them
def generateAll() -> None:
    processMobileReviews()
    config = mw.addonManager.getConfig(__name__)
    api_key = config.get("openai_api_key", "")
    if not api_key: 
        showInfo("Set your OpenAI api key in anki add on configuration")
        return
    search_query = "prop:due<=1 tag:requires note:GPT"
    card_ids = mw.col.findCards(search_query)
    for card_id in card_ids:
        card = mw.col.getCard(card_id)
        process_card(card, api_key)
    showInfo("Done Generating!")
# have Tools Menu option for generating cards that need to be generated
action = QAction("Generate & Handle Mobile", mw)
qconnect(action.triggered, generateAll)
mw.form.menuTools.addAction(action)

def processMobileReviews(): 
    search_query = "prop:due>1 tag:generated note:GPT"
    card_ids = mw.col.findCards(search_query)
    for card_id in card_ids:
        card = mw.col.getCard(card_id)
        handle_answer('', card, 3)


def call_openai(prompt, api_key):
    try: 
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gpt-4-turbo",  
            "messages": [
            {"role": "user", "content": prompt},
            ],
        }
        response = requests.post(url, headers=headers, json=payload)
        return response.json()['choices'][0]['message']['content']
    except requests.RequestException as e:
        print(f"An error occurred: {e}")
        return None

#all spreads should use the same 'Setting' since they differ from each other
#we want individual specific questions to differ by 'Setting' each time.
def process_card(card, api_key) -> None: 
    note = card.note()
    practice_set = field_set_parse(note["Recognition Practice Set"])
    settings = field_set_parse(note["Settings"])
    index = int(note["Index"])
    settingPrompt = ""
    if len(settings): 
        setting = settings[index]   
        settingPrompt = f"The setting/theme should be: {setting}"
    prompt = note["Prompt"] + "\n" + settingPrompt + "\n" + practice_set[0]
    generated_problem = call_openai(prompt, api_key)
    if generated_problem: 
        try: 
            note["Generated Practice"] = generated_problem
            note.addTag("generated")
            note.delTag("requires")
            mw.col.update_note(note)
        except Exception as e:
            showInfo(f"An error occurred: {e}")

def field_set_parse(input_str):
    entries = re.split(r'\d+\]', input_str)
    parsed_entries = [entry.strip() for entry in entries if entry.strip()]
    return parsed_entries

#Handling Answers
def set_requires(note) -> None: 
    note.addTag("requires")

def remove_spread_cards(note, ease) -> None: 
    if "spread" in note.tags and ease > 2: 
        mw.col.remNotes([note.id])
        return True

def create_spread_note(index, practice, note, card): 
    model = mw.col.models.byName("GPT")
    mw.col.models.setCurrent(model)  # set the model of the collection
    new_note = mw.col.newNote()  # now this note will use the "GPT" model
    new_note.addTag("requires")
    new_note.addTag("spread")
    new_note["Recognition Practice Set"] = re.sub('<br><br>$', '', practice.replace('&nbsp;', '').strip())
    new_note["Context"] = note["Context"]
    new_note["Prompt"] = note["Prompt"]
    new_note["Review Prompts"] = "SPREAD (review not required)" + "\n" + note["Review Prompts"]
    new_note["Settings"] = note["Settings"]
    new_note["Index"] = note["Index"]
    answers = field_set_parse(note["Answers"])
    if len(answers): 
        new_note["Answers"] = re.sub('<br><br>$', '', answers[index + 1].replace('&nbsp;', '').strip())
    deck_id = card.did
    new_note.model()['did'] = deck_id
    mw.col.addNote(new_note)
    return new_note

def create_spread_cards(note, card) -> None: 
    practice_set = field_set_parse(note["Recognition Practice Set"])
    if len(practice_set) < 2: #if only 1 problem type, no need for spreads
        return
    
    date_today = mw.col.sched.today
    date_due = card.due
    interval = (date_due - date_today) // len(practice_set)
    interval = interval if interval >= 1 else 1
    date_incrementer = date_today + interval
    
    for index, practice in enumerate(practice_set[1:]):
        new_note = create_spread_note(index, practice, note, card) 

        new_card_ids = new_note.card_ids()
        for new_card_id in new_card_ids:
            new_card = mw.col.getCard(new_card_id)

            new_card.type = 2 #due queue
            new_card.queue = 2
            new_card.due = date_incrementer

            new_card.flush()

        date_incrementer += interval
        if date_incrementer >= date_due: 
                date_incrementer = date_today + interval
 
def empty_practice(note) -> None: 
    note["Generated Practice"] = ""
    note.delTag("generated")

def handle_answer(reviewer, card, ease) -> None:    
    note = card.note()
    if card.queue != 2 or note.model()['name'] != 'GPT': #if card is not in review state (2), don't handle
        return
    #if card is a spread card, delete it
    if remove_spread_cards(note, ease) : 
        return 
    empty_practice(note)
    set_requires(note)

    #if non-spread card reviewed, create new spreads 
    if "spread" not in note.tags:
        create_spread_cards(note, card)
        index = int(note["Index"])
        settings = field_set_parse(note["Settings"])
        if index >= len(settings) - 1:
            note["Index"] = "0"
        else: 
            note["Index"] = str(index + 1)
    mw.col.update_note(note)
    
gui_hooks.reviewer_did_answer_card.append(handle_answer)
