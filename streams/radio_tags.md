# Radio Tags Configuration

## include
Tags to search in Radio Browser API (lumen_radio_extractor.py uses these):
- news
- talk
- speech
- information

## exclude

Stations with these words in tags OR name are excluded from radio_pool.json to catalog radio_catalog.csv by make_radio_catalog.py.
Case-insensitive substring matching. Use pipes as separators for clarity:

music|musica|música|musik|musique|muzica|mp3|musical|songs|song|playlist|dj|disco|club|schlager|pop|rock|dance|electronic|techno|house|hip hop|rap|jazz|classical|folk|country|rnb|metal|ambient|trance|reggae|latin|edm|indie|top 40|hits|oldies|1950s|1960s|1970s|1980s|50s|60s|70s|80s|entertainment|entretenimiento|variety|mixed|misc|community|tourism|travel|comedy|drama|documentary|documentaries|story|storytelling|children|kids|family|relationship|religion|catholic|islam|coran|christian|lgbt|gay|lesbian|queer|feminism|diversity|gender|erotik|bdsm|sex|adult|nagaswara|gospel|religious|worship|praise|instrumental|easy listening|christmas|sermon|prayer|spiritual|mpb|sertanejo|sertanejo raiz|brega|forró|forro|health|health programming|television|tv|conspiracies|conspiracy theories|survivalism|antisemitism|lifestyle|features|Mbiu

## include_countries

If specified, only stations from these countries are included during runtime validation.
If empty, all countries are accepted (except those in exclude_countries).
Case-insensitive country codes. Use pipes as separators (leave empty for no filtering):


## include_languages

If specified, only stations with these languages are included during runtime validation.
If empty, all languages are accepted (except those in exclude_languages).
Case-insensitive substring matching. Use pipes as separators (leave empty for no filtering):


## exclude_countries

Stations from these countries are excluded during runtime validation in lumen_generator.py.
Case-insensitive country codes. Use pipes as separators:

CN|KP

## exclude_languages

Stations with these languages are excluded during runtime validation in lumen_generator.py.
Case-insensitive substring matching. Use pipes as separators:

chinese|mandarin
