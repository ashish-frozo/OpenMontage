"""Deterministic transcript comparison. Recognition errors remain review candidates."""
import re

def words(text):
    return re.findall(r"\w+",text.casefold())

def compare_speech(reference,hypothesis):
    expected,actual=words(reference),words(hypothesis)
    if max(len(expected),len(actual))>10000: raise ValueError('Transcript comparison supports at most 10000 words')
    if not expected: raise ValueError('Reference script is empty')
    previous=list(range(len(actual)+1))
    for i,a in enumerate(expected,1):
        row=[i]
        for j,b in enumerate(actual,1):row.append(min(row[-1]+1,previous[j]+1,previous[j-1]+(a!=b)))
        previous=row
    return {'word_error_rate':previous[-1]/len(expected),'edit_distance':previous[-1],'reference_words':len(expected),'recognized_words':len(actual),
            'note':'ASR word differences are candidates; pronunciation, names and recognition errors require review.'}
