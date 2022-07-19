"""
The taxonomy being mapped to in the script needs to be in a specific format.
There should be the 3 columns skill_name_col, skill_id_col, skill_type_col
with an optional 4th column (skill_hier_info_col).
### Example 1:
At the most basic level your taxonomy input could be:
"name" | "id" | "type"
---|---|---
"driving a car" | 123 | "skill"
"give presentations" | 333 | "skill"
"communicating well" | 456 | "skill"
...
with skill_type_dict = {'skill_types': ['skill']}.
Your output match for the OJO skill "communicate" might look like this:
{
'ojo_ner_skills': "communicate",
'top_5_tax_skills': [("communicating well", 456, 0.978), ("give presentations", 333, 0.762), ..]
}
- the closest skill to this ojo skill is "communicating well" which is code 456 and had a cosine distance of 0.978
### Example 2:
A more complicated example would have hierarchy levels given too
"name" | "id" | "type" | "hierarchy_levels"
---|---|---|---
"driving a car" | 123 | "skill" | ['A2.1']
"give presentations" | 333 | "skill" | ['A1.2']
"communicating well" | 456 | "skill"| ['A1.3']
...
with skill_type_dict = {'skill_types': ['skill']}.
This might give the result:
{
'ojo_ner_skills': "communicate",
'top_5_tax_skills': [("communicating well", 456, 0.978), ("give presentations", 333, 0.762), ..],
'high_tax_skills':  {'num_over_thresh': 2, 'most_common_level_0: ('A1', 1) , 'most_common_level_1': ('A1.3', 0.5)},
}
- 100% of the skills where the similarity is greater than the threshold are in the 'A1' skill level 0 group
- 50% of the skills where the similarity is greater than the threshold are in the 'A1.3' skill level 1 group
### Example 3:
And an even more complicated example would have skill level names given too (making use
of the 'type' column to differentiate them).
"name" | "id" | "type" | "hierarchy_levels"
---|---|---|---
"driving a car" | 123 | "skill" | ['A2.1']
"give presentations" | 333 | "skill" | ['A1.2']
"communicating well" | 456 | "skill"| ['A1.3']
"communication" | 'A1' | "level 1"| None
"driving" | 'A2' | "level 0"| None
"communicate verbally" | 'A1.3' | "level 1"| None
...
with skill_type_dict = {'skill_types': ['skill'], 'hier_types': ["level A", "level B"]} and num_hier_levels=2
This might give the result:
{
'ojo_ner_skills': "communicate",
'top_5_tax_skills': [("communicating well", 456, 0.978), ("give presentations", 333, 0.762), ..],
'high_tax_skills':  {'num_over_thresh': 2, 'most_common_level_0: ('A1', 1) , 'most_common_level_1': ('A1.3', 0.5)},
"top_'level 0'_tax_level": ('communication', 'A1', 0.998),
"top_'level 1'_tax_level": ('communicate verbally', 'A1.3', 0.98),
}
- the skill level 0 group 'communication' (code 'A1') is the closest to thie ojo skill with distance 0.998
- the skill level 1 group 'communicate verbally' (code 'A1.3') is the closest to thie ojo skill with distance 0.98
"""

import sys

sys.path.append("/Users/india.kerlenesta/Projects/ojd_daps_extension/ojd_daps_skills/")

from ojd_daps_skills import config, bucket_name
from ojd_daps_skills.getters.data_getters import (
    get_s3_resource,
    load_s3_data,
    save_to_s3,
    get_s3_data_paths,
)
from ojd_daps_skills.pipeline.skill_ner_mapping.skill_ner_mapper_utils import (
    preprocess_skill,
    get_top_comparisons,
    get_most_common_code,
)
from ojd_daps_skills.utils.bert_vectorizer import BertVectorizer

from argparse import ArgumentParser
from sentence_transformers import SentenceTransformer
import re
import time
import itertools
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import os
import ast


class SkillMapper:
    """
    Class to map extracted skills from NER model to a skills taxonomy.
    Attributes
    ----------
    skill_name_col (str): the taxonomy column name of the description of the skill/skill level
    skill_id_col (str): the taxonomy column name of the id for the skill/skill level
    skill_hier_info_col (str, optional): the taxonomy column name of the ids for the skill levels the skill belongs to
    skill_type_col (str): the taxonomy column name for which type of data the row is from (specific skill or skill levels)
    bert_model_name (str): name of sentence transformer
    multi_process (bool): if vectoriser will multi_process
    batch_size (int): batch size
    ojo_skills_file_name (str): file name of extract ojo skills from ner model
    ----------
    Methods
    ----------
    get_ojo_skills(ojo_skills_file_name):
            loads extracted skills from NER model.
    preprocess_ojo_skills(ojo_skills):
            preprocess skills extracted OJO skills from NER model.
    preprocess_taxonomy_skills(taxonomy_skills):
            preprocesses list of taxonomy skills.
    load_bert:
            loads bert vectoriser.
    transform(skills):
            transforms skills.
    map_skills(taxonomy, taxonomy_skills, ojo_skills_file_name, num_hier_levels, skill_type_dict):
            loads taxonomy and OJO skills; preprocesses skills; embeds
            and maps OJO onto taxonomy skills based on cosine similarity.
    """

    def __init__(
        self,
        skill_name_col: "description",
        skill_id_col: "id",
        skill_hier_info_col: None,
        skill_type_col: "type",
        bert_model_name: "sentence-transformers/all-MiniLM-L6-v2",
        multi_process: True,
        batch_size: 32,
        ojo_skills_file_name: config["ojo_skills_ner_path"],
    ):
        self.skill_name_col = skill_name_col
        self.skill_id_col = skill_id_col
        self.skill_hier_info_col = skill_hier_info_col
        self.skill_type_col = skill_type_col
        self.bert_model_name = bert_model_name
        self.multi_process = multi_process
        self.batch_size = batch_size
        self.ojo_skills_file_name = ojo_skills_file_name

    def get_ojo_skills(self, ojo_skills_file_name):
        self.ojo_skills = load_s3_data(
            get_s3_resource(), bucket_name, self.ojo_skills_file_name
        )

        return self.ojo_skills

    def preprocess_ojo_skills(self, ojo_skills):
        self.ojo_job_ids = list(self.ojo_skills["predictions"].keys())
        self.clean_ojo_skills = dict()

        for ojo_job_id in self.ojo_job_ids:
            ojo_job_skills = self.ojo_skills["predictions"][ojo_job_id]["SKILL"]
            if ojo_job_skills != []:
                self.clean_ojo_skills[ojo_job_id] = {
                    "clean_skills": list(
                        set([preprocess_skill(skill) for skill in ojo_job_skills])
                    )
                }

        return self.clean_ojo_skills

    def preprocess_taxonomy_skills(self, taxonomy_skill_list):
        """
        For the sake of indexing its important that this function doesnt
        delete rows (input length == output length)
        """
        self.clean_taxonomy_skills = [
            preprocess_skill(skill) for skill in taxonomy_skill_list
        ]
        return self.clean_taxonomy_skills

    def transform(self, skills):
        # Load BERT model and transform skill
        skills_vec = self.bert_vectorizer.transform(skills)
        return skills_vec

    def map_skills(
        self, taxonomy_skills, ojo_skills_file_name, num_hier_levels, skill_type_dict
    ):
        """
        num_hier_levels (int): the number of levels there are in this taxonomy
        skill_type_dict (dict):
                A dictionary of the values of the skill_type_col column which fit into either the skill_types or the hier_types
                e.g. {'skill_types': ['preferredLabel', 'altLabels'], 'hier_types': ['Level 2 preferred term', 'Level 3 preferred term']}
        """

        self.ojo_skills = self.get_ojo_skills(self.ojo_skills_file_name)
        self.bert_vectorizer = BertVectorizer(
            bert_model_name=self.bert_model_name,
            multi_process=self.multi_process,
            batch_size=self.batch_size,
        )
        self.bert_vectorizer.fit()

        clean_tax_skills = self.preprocess_taxonomy_skills(
            taxonomy_skills[self.skill_name_col].tolist()
        )

        self.taxonomy_skills_embeddings = self.bert_vectorizer.transform(
            clean_tax_skills
        )

        clean_ojo_skills = self.preprocess_ojo_skills(self.ojo_skills)

        # Flatten the skills lists and keep track of the job ad and order of skills it was from
        flat_clean_ojo_skills = []
        flat_clean_ojo_skills_ix = []
        for job_id, skills in clean_ojo_skills.items():
            flat_clean_ojo_skills += skills["clean_skills"]
            flat_clean_ojo_skills_ix += [
                (job_id, skill_id) for skill_id, _ in enumerate(skills["clean_skills"])
            ]

        clean_ojo_skill_embeddings = self.bert_vectorizer.transform(
            flat_clean_ojo_skills
        )

        # Find the closest matches to skills information
        skill_types = skill_type_dict.get("skill_types", [])
        tax_skills_ix = taxonomy_skills[
            taxonomy_skills[self.skill_type_col].isin(skill_types)
        ].index
        (
            skill_top_sim_indxs,
            skill_top_sim_scores,
            skill_high_sim_indxs,
            skill_high_sim_scores,
        ) = get_top_comparisons(
            clean_ojo_skill_embeddings,
            self.taxonomy_skills_embeddings[tax_skills_ix],
            match_sim_thresh=0.5,
        )

        # Find the closest matches to the hierarchy levels information
        hier_types = {i: v for i, v in enumerate(skill_type_dict.get("hier_types", []))}
        hier_top_sims = {}
        for hier_type_ix, hier_type in hier_types.items():
            tax_hier_ix = taxonomy_skills[
                taxonomy_skills[self.skill_type_col] == hier_type
            ].index
            top_sim_indxs, top_sim_scores, _, _ = get_top_comparisons(
                clean_ojo_skill_embeddings, self.taxonomy_skills_embeddings[tax_hier_ix]
            )
            hier_top_sims[hier_type_ix] = {
                "top_sim_indxs": top_sim_indxs,
                "top_sim_scores": top_sim_scores,
                "tax_hier_ix": tax_hier_ix,
            }

        # Output the top matches (using the different metrics) for each OJO skill
        # Need to match indexes back correctly (hence all the ix variables)
        skill_mapper_dict = {}
        for match_i, match_text in enumerate(flat_clean_ojo_skills):

            # Top highest matches (any threshold)
            match_results = {
                "ojo_ner_skills": match_text,
                "top_5_tax_skills": list(
                    zip(
                        [
                            taxonomy_skills.iloc[tax_skills_ix[top_ix]][
                                self.skill_name_col
                            ]
                            for top_ix in skill_top_sim_indxs[match_i]
                        ],
                        [
                            taxonomy_skills.iloc[tax_skills_ix[top_ix]][
                                self.skill_id_col
                            ]
                            for top_ix in skill_top_sim_indxs[match_i]
                        ],
                        skill_top_sim_scores[match_i],
                    )
                ),
            }

            # Using the matches with similarity scores over a threshold, find the most common codes
            # for each level of the hierarchy (if hierarchy details are given)
            if self.skill_hier_info_col:
                high_hier_codes = []
                for sim_ix, sim_score in zip(
                    skill_high_sim_indxs[match_i], skill_high_sim_scores[match_i]
                ):
                    tax_info = taxonomy_skills.iloc[tax_skills_ix[sim_ix]]
                    hier_levels = ast.literal_eval(tax_info[self.skill_hier_info_col])
                    for hier_level in hier_levels:
                        high_hier_codes.append(hier_level)

                high_tax_skills_results = {
                    "num_over_thresh": len(skill_high_sim_indxs[match_i])
                }
                most_common_hier = {}
                for i in range(num_hier_levels):
                    high_tax_skills_results[
                        f"most_common_level_{i}"
                    ] = get_most_common_code(high_hier_codes, i)

                match_results["high_tax_skills"] = high_tax_skills_results

            # Now get the top matches using the hierarchy descriptions (if hier_types isnt empty)
            for hier_type_ix, hier_type in hier_types.items():
                hier_sim_id = hier_top_sims[hier_type_ix]
                tax_info = taxonomy_skills.iloc[
                    tax_hier_ix[hier_sim_id["top_sim_indxs"][match_i][0]]
                ]
                match_results[f"top_'{hier_type}'_tax_level"] = (
                    tax_info[self.skill_name_col],
                    tax_info[self.skill_id_col],
                    hier_sim_id["top_sim_scores"][match_i][0],
                )

            job_id, skill_num = flat_clean_ojo_skills_ix[match_i]
            skill_mapper_dict[job_id] = match_results

        return skill_mapper_dict


if __name__ == "__main__":

    parser = ArgumentParser()

    parser.add_argument(
        "--taxonomy",
        help="Name of taxonomy to be mapped to.",
        default="esco",
    )

    parser.add_argument(
        "--ojo_skill_fn",
        help="Name of ojo skills file name to be mapped to.",
        default=config["ojo_skills_ner_path"],
    )

    args = parser.parse_args()

    taxonomy = args.taxonomy
    ojo_skill_file_name = args.ojo_skill_fn

    # Hard code how many levels there are in the taxonomy (if any)
    if taxonomy == "esco":
        num_hier_levels = 3
        skill_type_dict = {
            "skill_types": ["preferredLabel", "altLabels"],
            "hier_types": ["Level 2 preferred term", "Level 3 preferred term"],
        }
        tax_input_file_name = (
            "escoe_extension/outputs/data/skill_ner_mapping/esco_data_formatted.csv"
        )
    else:
        num_hier_levels = 0
        skill_type_dict = {}
        tax_input_file_name = ""

    skill_mapper = SkillMapper(
        skill_name_col="description",
        skill_id_col="id",
        skill_hier_info_col="hierarchy_levels",
        skill_type_col="type",
        bert_model_name="sentence-transformers/all-MiniLM-L6-v2",
        multi_process=True,
        batch_size=32,
        ojo_skills_file_name=config["ojo_skills_ner_path"],
    )

    taxonomy_skills = load_s3_data(get_s3_resource(), bucket_name, tax_input_file_name)

    skills_to_taxonomy = skill_mapper.map_skills(
        taxonomy_skills,
        ojo_skill_file_name,
        num_hier_levels=num_hier_levels,
        skill_type_dict=skill_type_dict,
    )

    skill_mapper_file_name = (
        ojo_skill_file_name.split("/")[-1].split(".")[0] + "_to_" + taxonomy + ".json"
    )

    save_to_s3(
        get_s3_resource(),
        bucket_name,
        skills_to_taxonomy,
        os.path.join(config["ojo_skills_ner_mapping_dir"], skill_mapper_file_name),
    )
