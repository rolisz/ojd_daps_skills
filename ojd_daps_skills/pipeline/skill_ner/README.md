# Skill NER

## Label data

### Creating a sample of the OJO data

We first create a sample of job adverts to label.

First, connected to the Nesta VPN and in your activated conda environment, export your SQL credentials location to an environmental variable:

```
export SQL_DB_CREDS="$HOME/path/to/mysqldb_team_ojo_may22.config"
```

Then run the script with:

```
python ojd_daps_skills/pipeline/skill_ner/create_data_sample.py --sample_size 5000
```

The random sample of job adverts created from this will be stored in S3 in the `open-jobs-lake` bucket in the `/escoe_extension/inputs/data/skill_ner/data_sample/` folder.

### Processing the job adverts

After creating this random sample we process it into a form suitable for labelling in label-studio.

Back to this `ojd_daps_skills` repo and conda environment, this processing is done by running:

```
python ojd_daps_skills/pipeline/skill_ner/create_label_data.py
```

An output file which can be inputted into label-studio (the descriptions from the job advert sample) is stored in `s3://open-jobs-lake/escoe_extension/inputs/data/skill_ner/20220623_sample_labelling_text_data.txt`, and a sister file which maps the job advert text to the job ID of the advert they were in is stored in `s3://open-jobs-lake/escoe_extension/inputs/data/skill_ner/20220623_sample_labelling_metadata.json`. This latter file is important for any analysis of the sample data since we can link back to the job advert's metadata, so could analysis which years/job occupations the sample came from.

### Labelling

There are 3 labels:

1. SKILL
2. MULTISKILL
3. EXPERIENCE

- Label all the skills by dragging from the start of where the skill is mentioned to the end, then press `SUBMIT`.
  ![](./ner_label_examples/label_eg1.jpg)
- If there are no skills in the sentence press `SUBMIT`.
  ![](./ner_label_examples/label_eg5.jpg)
- Try to label each skill separately with a `SKILL` label, but if this isn't possible use the `MULTISKILL` tag.
  ![](./ner_label_examples/label_eg4.jpg)
- `EXPERIENCE` labels will often be followed by "experience" e.g. "insurance experience".
- `EXPERIENCE` labels also include qualifications, e.g. "Electrical qualifications".
- If its just "have a degree" then this shouldn't be labelled, but if it is "have a maths degree" then "maths" can be labelled as a `SKILL`
- `MULTISKILL` labels will often be when you need an earlier part of the sentence to define the later part
- When labelling spans try to start at the verb

When to `SKIP`:

- Anything which is too hard to label where you think you'll make bad mistakes then `SKIP`
- If you aren't sure then `SKIP`.
- If the text is badly formatted to the extent its hard to label then `SKIP`
  ![](./ner_label_examples/label_eg6.jpg)

We don't want bad labels in our training data

Be careful:

- To include the whole span of the skill(s). Try not to make sure you havent cut any characters off or added any.
- Try to to include trailing whitespace in the spans

#### label-studio options

- Random sampling
- SKILL, MULTISKILL, EXPERIENCE label
- "Select text by words" selected
- "Add filter for long list of labels" NOT selected