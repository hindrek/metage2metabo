#!/usr/bin/env python
# Copyright (c) 2019, Clemence Frioux <clemence.frioux@inria.fr>
#
# This file is part of metage2metabo.
#
# metage2metabo is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# metage2metabo is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with metage2metabo.  If not, see <http://www.gnu.org/licenses/>.
# -*- coding: utf-8 -*-

import csv
import json
import miscoto
import networkx as nx
import os
import shutil
import sys
import time
import subprocess
import logging
import zipfile

from bubbletools import convert
from ete3 import NCBITaxa
from itertools import combinations
from metage2metabo import utils, sbml_management

logger = logging.getLogger(__name__)
logging.getLogger("miscoto").setLevel(logging.CRITICAL)


def file_or_folder(variable_folder_file):
    """Check if the variable is file or a folder

    Args:
        variable_folder_file (str): path to a file or a folder

    Returns:
        dict: {name of input file: path to input file}
    """
    file_folder_paths = {}

    if os.path.isfile(variable_folder_file):
        filename = os.path.splitext(os.path.basename(variable_folder_file))[0]
        file_folder_paths[filename] = variable_folder_file

    # For folder, iterate through all files inside the folder.
    elif os.path.isdir(variable_folder_file):
        for file_from_folder in os.listdir(variable_folder_file):
            filename = os.path.splitext(os.path.basename(file_from_folder))[0]
            file_folder_paths[filename] = os.path.join(variable_folder_file, file_from_folder)

    return file_folder_paths


def run_analysis_workflow(sbml_folder, target_folder_file, seed_file, output_dir, taxon_file, oog_jar, host_file=None):
    """Run the whole m2m_analysis workflow

    Args:
        sbml_folder (str): sbml directory
        target_folder_file (str): targets file or folder containing multiple sbmls
        seed_file (str): seeds file
        output_dir (str): results directory
        taxon_file (str): mpwt taxon file for species in sbml folder
        oog_jar (str): path to OOG jar file
        host_file (str): metabolic network file for host
    """
    starttime = time.time()

    json_file_folder = enumeration_analysis(sbml_folder, target_folder_file, seed_file, output_dir, host_file)

    gml_output = graph_analysis(json_file_folder, target_folder_file, output_dir, taxon_file)

    powergraph_analysis(output_dir, oog_jar, taxon_file)

    logger.info(
        "--- m2m_analysis runtime %.2f seconds ---\n" % (time.time() - starttime))

def enumeration(sbml_folder, target_file, seed_file, output_json, host_file):
    """Run miscoto enumeration on one target file

    Args:
        sbml_folder (str): sbml directory
        target_file (str): targets file
        seed_file (str): seeds file
        output_json (str): path to json output
        host_file (str): metabolic network file for host

    Returns:
        str: path to output json
    """
    results = miscoto.run_mincom(option="soup", bacteria_dir=sbml_folder,
        targets_file=target_file, seeds_file=seed_file,
        host_file=host_file, intersection=True,
        enumeration=True, union=True,
        optsol=True, output_json=output_json)

    # Give enumeration of solutions
    enumeration = str(len(results['enum_bacteria']))
    minimal_solution_size = str(len(results["bacteria"]))
    logger.info('######### Enumeration of minimal communities #########')
    logger.info(enumeration + ' minimal communities (each containing ' + minimal_solution_size + ' species) producing the target metabolites')
    # Give union of solutions
    union = results['union_bacteria']
    logger.info('######### Key species: Union of minimal communities #########')
    logger.info("# Bacteria occurring in at least one minimal community enabling the producibility of the target metabolites given as inputs")
    logger.info("Key species = " +
                str(len(union)))
    logger.info("\n".join(union))
    # Give intersection of solutions
    intersection = results['inter_bacteria']
    logger.info('######### Essential symbionts: Intersection of minimal communities #########')
    logger.info("# Bacteria occurring in ALL minimal community enabling the producibility of the target metabolites given as inputs")
    logger.info("Essential symbionts = " +
                str(len(intersection)))
    logger.info("\n".join(intersection))
    # Give key species, essential and alternative symbionts
    alternative_symbionts = list(set(union) - set(intersection))
    logger.info('######### Alternative symbionts: Difference between Union and Intersection #########')
    logger.info("# Bacteria occurring in at least one minimal community but not all minimal community enabling the producibility of the target metabolites given as inputs")
    logger.info("Alternative symbionts = " +
                str(len(alternative_symbionts)))
    logger.info("\n".join(alternative_symbionts))

    return output_json


def enumeration_analysis(sbml_folder, target_folder_file, seed_file, output_dir, host_file=None):
    """Run miscoto enumeration on input data

    Args:
        sbml_folder (str): sbml directory
        target_folder_file (str): targets file or folder containing multiple sbmls
        seed_file (str): seeds file
        output_dir (str): results directory
        host_file (str): metabolic network file for host

    Returns:
        dict: {target_filename_without_extension: json_output_path}
    """
    starttime = time.time()

    target_paths = file_or_folder(target_folder_file)

    output_jsons = os.path.join(output_dir, 'json')
    if not utils.is_valid_dir(output_jsons):
        logger.critical("Impossible to access/create output directory")
        sys.exit(1)

    miscoto_jsons = {}
    for target_path in target_paths:
        logger.info('######### Enumeration of solution for: '+ target_path + ' #########')
        target_pathname = target_paths[target_path]
        output_json = os.path.join(output_jsons, target_path + '.json')
        miscoto_json = enumeration(sbml_folder, target_pathname, seed_file, output_json, host_file)
        miscoto_jsons[target_path] = miscoto_json

    logger.info(
        "--- Enumeration runtime %.2f seconds ---\n" % (time.time() - starttime))

    return output_jsons


def stat_analysis(json_file_folder, output_dir, taxon_file=None):
    """Run the analysis part of the workflow on miscoto enumeration jsons

    Args:
        json_file_folder (str): json file or folder containing multiple jsons
        output_dir (str): results directory
        taxon_file (str): mpwt taxon file for species in sbml folder
    """
    starttime = time.time()

    miscoto_stat_output = os.path.join(output_dir, 'miscoto_stats.txt')
    key_species_stats_output = os.path.join(output_dir, 'key_species_stats.tsv')
    key_species_supdata_output = os.path.join(output_dir, 'key_species_supdata.tsv')
    json_paths = file_or_folder(json_file_folder)

    if taxon_file:
        c
        tree_output_file = os.path.join(output_dir, 'taxon_tree.txt')
        extract_taxa(taxon_file, phylum_output_file, tree_output_file)
        phylum_species, all_phylums = get_phylum(phylum_output_file)
    else:
        phylum_species = None
        all_phylums = None

    with open(key_species_stats_output, "w") as key_stats_file, open(
        key_species_supdata_output, "w"
    ) as key_sup_file, open(miscoto_stat_output, "w") as stats_output:
        key_stats_writer = csv.writer(key_stats_file, delimiter="\t")
        if all_phylums:
            key_stats_writer.writerow(["target_categories", "key_group", *sorted(all_phylums), "Sum"])
        else:
            key_stats_writer.writerow(["target_categories", "key_group", "data", "Sum"])
        key_sup_writer = csv.writer(key_sup_file, delimiter="\t")
        statswriter = csv.writer(stats_output, delimiter="\t")
        statswriter.writerow(["categories", "nb_target", "size_min_sol", "size_union", "size_intersection", "size_enum"])
        for json_path in json_paths:
            with open(json_paths[json_path]) as json_data:
                json_elements = json.load(json_data)
            create_stat_species(json_path, json_elements, key_stats_writer, key_sup_writer, phylum_species, all_phylums)
            statswriter.writerow([json_path, str(len(json_elements["newly_prod"]) + len(json_elements["still_unprod"])),
									str(len(json_elements["bacteria"])), str(len(json_elements["union_bacteria"])),
                    				str(len(json_elements["inter_bacteria"])), str(len(json_elements["enum_bacteria"]))])

    logger.info(
        "--- Stats runtime %.2f seconds ---\n" % (time.time() - starttime))


def graph_analysis(json_file_folder, target_folder_file, output_dir, taxon_file):
    """Run the graph creation on miscoto output

    Args:
        json_file_folder (str): json file or folder containing multiple jsons
        target_folder_file (str): targets file or folder containing multiple sbmls
        output_dir (str): results directory
        taxon_file (str): mpwt taxon file for species in sbml folder

    Returns:
        str: path to folder containing gml results
    """
    starttime = time.time()

    target_paths = file_or_folder(target_folder_file)
    json_paths = file_or_folder(json_file_folder)

    gml_output = os.path.join(output_dir, 'gml')

    if taxon_file:
        phylum_output_file = os.path.join(output_dir, 'taxon_phylum.tsv')
        tree_output_file = os.path.join(output_dir, 'taxon_tree.txt')
        if not os.path.exists(phylum_output_file):
            extract_taxa(taxon_file, phylum_output_file, tree_output_file)
    else:
        phylum_output_file = None

    create_gml(json_paths, target_paths, output_dir, phylum_output_file)

    logger.info(
        "--- Graph runtime %.2f seconds ---\n" % (time.time() - starttime))

    return gml_output


def powergraph_analysis(m2m_analysis_folder, oog_jar=None, taxon_file=None):
    """Run the graph compression and picture creation

    Args:
        m2m_analysis_folder (str): m2m analysis directory with gml files
        oog_jar (str): path to OOG jar file
        taxon_file (str): mpwt taxon file for species in sbml folder
    """
    starttime = time.time()

    gml_folder = os.path.join(m2m_analysis_folder, 'gml')
    gml_paths = file_or_folder(gml_folder)

    bbl_path = os.path.join(m2m_analysis_folder, 'bbl')
    svg_path = os.path.join(m2m_analysis_folder, 'svg')
    html_output = os.path.join(m2m_analysis_folder, 'html')

    if not utils.is_valid_dir(bbl_path):
        logger.critical("Impossible to access/create output directory " + bbl_path)
        sys.exit(1)

    if oog_jar:
        if not utils.is_valid_dir(svg_path):
            logger.critical("Impossible to access/create output directory " +  svg_path)
            sys.exit(1)

    if not utils.is_valid_dir(html_output):
        logger.critical("Impossible to access/create output directory " + html_output)
        sys.exit(1)

    es_as_for_tagets = find_essential_alternatives(m2m_analysis_folder, taxon_file)

    # 25 colours from Alphabet project (minus white):
    # https://en.wikipedia.org/wiki/Help:Distinguishable_colors
    yrdy_olors = ["#F0A3FF",
        "#0075DC",
        "#993F00",
        "#4C005C",
        "#191919",
        "#005C31",
        "#2BCE48",
        "#FFCC99",
        "#808080",
        "#94FFB5",
        "#8F7C00",
        "#9DCC00",
        "#C20088",
        "#003380",
        "#FFA405",
        "#FFA8BB",
        "#426600",
        "#FF0010",
        "#5EF1F2",
        "#00998F",
        "#E0FF66",
        "#740AFF",
        "#990000",
        "#FFFF80",
        "#FFFF00",
        "#FF5005"]

    if taxon_file:
        phylum_file = os.path.join(m2m_analysis_folder, 'taxon_phylum.tsv')
        phylum_species, all_phylums = get_phylum(phylum_file)
        phylum_colors = {}
        for index, phylum in enumerate(all_phylums):
            phylum_colors[phylum] = yrdy_olors[index]

    for gml_path in gml_paths:
        bbl_output = os.path.join(bbl_path, gml_path + '.bbl')
        svg_file = os.path.join(svg_path, gml_path + '.bbl.svg')

        html_target = os.path.join(html_output, gml_path)
        if not utils.is_valid_dir(html_target):
            logger.critical("Impossible to access/create output directory " + html_target)
            sys.exit(1)

        gml_input = gml_paths[gml_path]
        logger.info('######### Graph compression: ' + gml_path + ' #########')
        compression(gml_input, bbl_output)
        logger.info('######### PowerGraph visualization: ' + gml_path + ' #########')

        essentials = es_as_for_tagets[gml_path]['essential_symbionts']
        alternatives = es_as_for_tagets[gml_path]['alternative_symbionts']

        bbl_to_html(bbl_output, html_target)
        if taxon_file:
            if os.path.exists(html_target +'_taxon'):
                shutil.rmtree(html_target +'_taxon')
            shutil.copytree(html_target, html_target +'_taxon')
            update_js_taxonomy(html_target +'_taxon', phylum_colors)
        update_js(html_target, essentials, alternatives)

        if oog_jar:
            bbl_to_svg(oog_jar, bbl_output, svg_path)
            if taxon_file:
                taxonomy_svg_file = os.path.join(svg_path, gml_path + '_taxon.bbl.svg')
                shutil.copyfile(svg_file, taxonomy_svg_file)
                update_svg_taxonomy(taxonomy_svg_file, phylum_colors)
            update_svg(svg_file, essentials, alternatives)

    logger.info(
        "--- Powergraph runtime %.2f seconds ---\n" % (time.time() - starttime))


def extract_taxa(mpwt_taxon_file, taxon_output_file, tree_output_file):
    """From NCBI taxon ID, extract taxonomy rank and create a tree file

    Args:
        mpwt_taxon_file (str): mpwt taxon file for species in sbml folder
        taxon_output_file (str): path to phylum output file
        tree_output_file (str): path to tree output file

    """
    ncbi = NCBITaxa()

    taxon_ids = []

    phylum_count = {}
    with open(taxon_output_file, "w") as phylum_file:
        csvwriter = csv.writer(phylum_file, delimiter="\t")
        csvwriter.writerow(["species", "taxid", "phylum_number", "phylum", "class", "order", "family", "genus", "species"])
        with open(mpwt_taxon_file, "r") as taxon_file:
            csvfile = csv.reader(taxon_file, delimiter="\t")
            for line in csvfile:
                if "taxon" not in line[1]:
                    taxon_ids.append(line[1])
                    lineage = ncbi.get_lineage(line[1])
                    lineage2ranks = ncbi.get_rank(lineage)
                    names = ncbi.get_taxid_translator(lineage)
                    ranks2lineage = dict((rank, names[taxid]) for (taxid, rank) in lineage2ranks.items())
                    ranks = [ranks2lineage.get(rank, "no_information") for rank in ["phylum", "class", "order", "family", "genus", "species"]]
                    if ranks[0] != "no_information":
                        phylum = ranks[0][:4]
                    else:
                        phylum = "no_information"
                    if phylum not in phylum_count:
                        phylum_count[phylum] = 1
                    elif phylum == "no_information":
                        phylum_count[phylum] = ""
                    else:
                        phylum_count[phylum] += 1
                    row = ([line[0], line[1]] + [phylum + str(phylum_count[phylum])] + ranks)
                    csvwriter.writerow(row)

    tree = ncbi.get_topology(taxon_ids)

    with open(tree_output_file, "w") as tree_file:
        tree_file.write(tree.get_ascii(attributes=["sci_name", "rank"]))


def detect_phylum_species(phylum_named_species, all_phylums):
    """From a list of species named after their phylum, return a dictionary of {Phylum: [species_1, species_2]}

    Args:
        phylum_named_species (dict): {species_ID: species_named_after_phylum}
        all_phylums (list): all phylum in the dataset

    Returns:
        dict: {Phylum: [species_1, species_2]}
    """
    phylum_species = {}
    for phylum in phylum_named_species:
        if phylum[:4] not in phylum_species:
            phylum_species[phylum[:4]] = [phylum_named_species[phylum]]
        else:
            phylum_species[phylum[:4]].append(phylum_named_species[phylum])

    for phylum in all_phylums:
        if phylum not in phylum_species:
            phylum_species[phylum[:4]] = []

    return phylum_species


def detect_key_species(json_elements, all_phylums, phylum_named_species=None):
    """Detect key species (essential and alternative symbionts) from the miscoto json

    Args:
        json_elements (dict): miscoto results in a json dictionary
        all_phylums (list): all phylum in the dataset
        phylum_named_species (dict): {species_ID: species_named_after_phylum}

    Returns:
        key_species (dict): {Phylum: [species_1, species_2]}
        essential_symbionts (dict): {Phylum: [species_1, species_2]}
        alternative_symbionts (dict): {Phylum: [species_1, species_2]}
    """
    if phylum_named_species:
        unions = {phylum_named_species[species_union]: species_union
            		for species_union in json_elements["union_bacteria"]}
        intersections = {phylum_named_species[species_intersection]: species_intersection
            		for species_intersection in json_elements["inter_bacteria"]}
    else:
        unions = json_elements["union_bacteria"]
        intersections = json_elements["inter_bacteria"]

    if phylum_named_species:
        key_species = detect_phylum_species(unions, all_phylums)
        essential_symbionts = detect_phylum_species(intersections, all_phylums)
        alternative_symbionts = {}
        for phylum in key_species:
            alternative_symbionts[phylum] = list(set(key_species[phylum]) - set(essential_symbionts[phylum]))
        for phylum in all_phylums:
            if phylum not in alternative_symbionts:
                alternative_symbionts[phylum] = []
    else:
        key_species = {}
        essential_symbionts = {}
        alternative_symbionts = {}
        key_species["data"] = unions
        essential_symbionts["data"] = intersections
        alternative_symbionts["data"] = list(set(unions) - set(intersections))

    return key_species, essential_symbionts, alternative_symbionts


def create_stat_species(target_category, json_elements, key_stats_writer, key_sup_writer, phylum_named_species=None, all_phylums=None):
    """Write stats on key species (essential and alternative symbionts) from the miscoto json

    Args:
        target_category (str): name of a target file (without extension)
        json_elements (dict): miscoto results in a json dictionary
        key_stats_writer (csv.writer): writer for stats of each group (key species) in each phylum
        key_sup_writer (csv.writer): writer for all key species in each phylum
        phylum_named_species (dict): {species_ID: species_named_after_phylum}
        all_phylums (list): all phylum in the dataset
    """
    key_stone_species, essential_symbionts, alternative_symbionts = detect_key_species(json_elements, all_phylums, phylum_named_species)

    key_stone_counts = [len(key_stone_species[phylum]) for phylum in sorted(list(key_stone_species.keys()))]
    key_stats_writer.writerow([target_category, "key_species"] + key_stone_counts + [sum(key_stone_counts)])

    essential_symbiont_counts = [len(essential_symbionts[phylum]) for phylum in sorted(list(essential_symbionts.keys()))]
    key_stats_writer.writerow([target_category, "essential_symbionts"] + essential_symbiont_counts + [sum(essential_symbiont_counts)])

    alternative_symbiont_counts = [len(alternative_symbionts[phylum]) for phylum in sorted(list(alternative_symbionts.keys()))]
    key_stats_writer.writerow([target_category, "alternative_symbionts"] + alternative_symbiont_counts + [sum(alternative_symbiont_counts)])

    if all_phylums:
        for phylum in sorted(all_phylums):
            key_sup_writer.writerow([target_category, "key_stone_species", phylum] + key_stone_species[phylum])
            key_sup_writer.writerow([target_category, "essential_symbionts", phylum] + essential_symbionts[phylum])
            key_sup_writer.writerow([target_category, "alternative_symbionts", phylum] + alternative_symbionts[phylum])
    else:
        key_sup_writer.writerow([target_category, "key_stone_species", "data"] + key_stone_species["data"])
        key_sup_writer.writerow([target_category, "essential_symbionts", "data"] + essential_symbionts["data"])
        key_sup_writer.writerow([target_category, "alternative_symbionts", "data"] + alternative_symbionts["data"])


def get_phylum(phylum_file):
    """From the phylum file (created by extract_taxa) create a dictionary and a list linking phylum and species

    Args:
        phylum_file (str): path to the phylum_file
    """
    phylum_named_species = {}
    all_phylums = []
    with open(phylum_file, "r") as phylum_file:
        phylum_reader = csv.reader(phylum_file, delimiter="\t", quotechar="|")
        for row in phylum_reader:
            phylum_named_species[row[0]] = row[2]
            if row[2][:4] not in all_phylums:
                if "no_information" not in row[2] and "phylum_number" not in row[2]:
                    all_phylums.append(row[2][:4])

    return phylum_named_species, all_phylums


def create_gml(json_paths, target_paths, output_dir, taxon_file=None):
    """Create solution graph from miscoto output and compute stats

    Args:
        json_paths (str): {target: path_to_corresponding_json}
        target_paths (str): {target: path_to_corresponding_sbml}
        output_dir (str): results directory
        taxon_file (str): mpwt taxon file for species in sbml folder
    """
    miscoto_stat_output = os.path.join(output_dir, 'miscoto_stats.txt')
    key_species_stats_output = os.path.join(output_dir,'key_species_stats.tsv')
    key_species_supdata_output = os.path.join(output_dir, 'key_species_supdata.tsv')

    gml_output = os.path.join(output_dir, 'gml')

    if not utils.is_valid_dir(gml_output):
        logger.critical('Impossible to access/create output directory')
        sys.exit(1)

    len_min_sol = {}
    len_union = {}
    len_intersection = {}
    len_solution = {}
    len_target = {}

    target_categories = {}
    for target in target_paths:
        target_categories[target] = sbml_management.get_compounds(target_paths[target])

    if taxon_file:
        phylum_named_species, all_phylums = get_phylum(taxon_file)
    else:
        phylum_named_species = None
        all_phylums = None

    with open(key_species_stats_output, 'w') as key_stats_file, open(key_species_supdata_output, 'w') as key_sup_file, open(miscoto_stat_output, 'w') as stats_output:
        key_stats_writer = csv.writer(key_stats_file, delimiter='\t')
        if all_phylums:
            key_stats_writer.writerow(['target_categories', 'key_group', *sorted(all_phylums), 'Sum'])
        else:
            key_stats_writer.writerow(['target_categories', 'key_group', 'data', 'Sum'])
        key_sup_writer = csv.writer(key_sup_file, delimiter='\t')
        for target_category in target_categories:
            target_output_gml_path = os.path.join(gml_output, target_category + '.gml')
            with open(json_paths[target_category]) as json_data:
                dicti = json.load(json_data)
            create_stat_species(target_category, dicti, key_stats_writer, key_sup_writer, phylum_named_species, all_phylums)
            G = nx.Graph()
            added_node = []
            species_weight = {}
            if dicti['still_unprod'] != []:
                logger.warning('ERROR ', dicti["still_unprod"], ' is unproducible')
            len_target[target_category] = len(dicti['newly_prod']) + len(dicti['still_unprod'])
            len_min_sol[target_category] = len(dicti['bacteria'])
            len_union[target_category] = len(dicti['union_bacteria'])
            len_intersection[target_category] = len(dicti['inter_bacteria'])
            len_solution[target_category] = len(dicti['enum_bacteria'])
            for sol in dicti['enum_bacteria']:
                for species_1, species_2 in combinations(
                    dicti['enum_bacteria'][sol], 2
                ):
                    if species_1 not in added_node:
                        if taxon_file:
                            G.add_node(phylum_named_species[species_1])
                        else:
                            G.add_node(species_1)
                        added_node.append(species_1)
                    if species_2 not in added_node:
                        if taxon_file:
                            G.add_node(phylum_named_species[species_2])
                        else:
                            G.add_node(species_2)
                        added_node.append(species_2)
                    combination_species = '_'.join(sorted([species_1, species_2]))
                    if combination_species not in species_weight:
                        species_weight[combination_species] = 1
                    else:
                        species_weight[combination_species] += 1
                    if taxon_file:
                        G.add_edge(phylum_named_species[species_1], phylum_named_species[species_2], weight=species_weight[combination_species])
                    else:
                        G.add_edge(species_1, species_2, weight=species_weight[combination_species])

            statswriter = csv.writer(stats_output, delimiter="\t")
            statswriter.writerow(['categories', 'nb_target', 'size_min_sol', 'size_union', 'size_intersection', 'size_enum'])
            statswriter.writerow([target_category, str(len_target[target_category]), str(len_min_sol[target_category]),
                                    str(len_union[target_category]), str(len_intersection[target_category]),
                                    str(len_solution[target_category])])
            logger.info('######### Graph of ' + target_category + ' #########')
            logger.info('Number of nodes: ' + str(G.number_of_nodes()))
            logger.info('Number of edges: ' + str(G.number_of_edges()))
            nx.write_gml(G, target_output_gml_path)


def compression(gml_input, bbl_output):
    """Solution graph compression

    Args:
        gml_input (str): gml file
        bbl_output (str): bbl output file
    """
    starttime = time.time()
    with open('powergrasp.cfg', 'w') as config_file:
        config_file.write('[powergrasp options]\n')
        config_file.write('SHOW_STORY = no\n')

    import powergrasp
    from bubbletools import BubbleTree

    with open(bbl_output, 'w') as fd:
        for line in powergrasp.compress_by_cc(gml_input):
            fd.write(line + '\n')

    tree = BubbleTree.from_bubble_file(bbl_output)
    logger.info('Number of powernodes: ' + str(len([powernode for powernode in tree.powernodes()])))
    logger.info('Number of poweredges: ' + str(tree.edge_number()))

    os.remove('powergrasp.cfg')

    logger.info(
        'Compression runtime %.2f seconds ---\n' % (time.time() - starttime))


def check_oog_jar_file(oog_jar):
    """Check Oog jar file

    Args:
        oog_jar (str): path to oog jar file
    """
    if not os.path.isfile(oog_jar):
        sys.exit('Check Oog.jar: ' + oog_jar + ' is not an available file.')

    try:
        jarfile = zipfile.ZipFile(oog_jar, "r")
    except zipfile.BadZipFile:
        sys.exit('Check Oog.jar: ' + oog_jar + ' is not a valid .jar file (as it is not a correct zip file).')

    oog_class = None
    manifest_jar = None

    for filename in jarfile.namelist():
        if filename.endswith('Oog.class'):
            oog_class = True
        if filename.endswith('MANIFEST.MF'):
            manifest_jar = True

    jarfile.close()

    if oog_class and manifest_jar:
        return True
    elif manifest_jar:
        logger.info('Check Oog.jar: no correct Oog.class in jar file ' + oog_jar)
        return True
    else:
        sys.exit('Check Oog.jar: not a correct jar file ' + oog_jar)


def bbl_to_html(bbl_input, html_output):
    """Powergraph website creation.
    This create a folder with html/CSS/JS files. By using the index.html file in a browser, user can see the powergraph.

    Args:
        bbl_input (str): bbl input file
        svg_output (str): html output file
    """
    logger.info('######### Creation of the powergraph website accessible at ' + html_output + ' #########')
    convert.bubble_to_js(bbl_input, html_output)


def bbl_to_svg(oog_jar, bbl_input, svg_output):
    """Powergraph picture creation

    Args:
        oog_jar (str): path to oog jar file
        bbl_input (str): bbl input file
        svg_output (str): svg output file
    """
    check_oog = check_oog_jar_file(oog_jar)

    if check_oog:
        logger.info('######### Creation of the powergraph svg accessible at ' + svg_output + ' #########')
        oog_cmds = ["java", "-jar", oog_jar, "-inputfiles=" + bbl_input, "-img", "-outputdir=" + svg_output]
        subproc = subprocess.Popen(oog_cmds)
        subproc.wait()


def find_essential_alternatives(output_folder, taxon_file):
    key_species_file = os.path.join(output_folder, 'key_species_supdata.tsv')

    es_as_for_tagets = {}
    with open(key_species_file, 'r') as input_file:
        csvreader = csv.reader(input_file, delimiter='\t')
        for row in csvreader:
            target = row[0]
            if target not in es_as_for_tagets:
                es_as_for_tagets[target] = {}
            if row[1] in ['essential_symbionts', 'alternative_symbionts']:
                if row[1] not in es_as_for_tagets[target]:
                    es_as_for_tagets[target][row[1]] = row[3:]
                else:
                    es_as_for_tagets[target][row[1]].extend(row[3:])

    es_as_for_tagets[target]['essential_symbionts'] = list(set(es_as_for_tagets[target]['essential_symbionts']))
    es_as_for_tagets[target]['alternative_symbionts'] = list(set(es_as_for_tagets[target]['alternative_symbionts']))

    if taxon_file:
        phylum_file = os.path.join(output_folder, 'taxon_phylum.tsv')
        phylum_species, all_phylums = get_phylum(phylum_file)

        for target in es_as_for_tagets:
            es_as_for_tagets[target]['essential_symbionts'] = [phylum_species[species] for species in es_as_for_tagets[target]['essential_symbionts']]
            es_as_for_tagets[target]['alternative_symbionts'] = [phylum_species[species] for species in es_as_for_tagets[target]['alternative_symbionts']]

    return es_as_for_tagets


def update_js(html_output, essentials, alternatives):
    selector_color = '''
    {
        selector: 'node[type="essential"]',
        css: {
            'background-color': 'green',
        }
    },
    {
        selector: 'node[type="alternative"]',
        css: {
            'background-color': 'blue',
        }
    },
    '''

    js_folder = os.path.join(html_output, 'js')
    graph_js = os.path.join(js_folder, 'graph.js')
    new_graph_sj = ''
    with open(graph_js, 'r') as input_js:
        for line in input_js:
            if "data: { 'id'" in line:
                species_id = line.split("'id':")[1].split(',')[0].strip("'| ")
                if species_id in essentials:
                    line = line.replace(" } },", ", 'type': 'essential' } },")
                if species_id in alternatives:
                    line = line.replace(" } },", ", 'type': 'alternative' } },")
            new_graph_sj += line
            if 'style: [' in line:
                new_graph_sj += selector_color

    with open(graph_js, 'w') as input_js:
        input_js.write(new_graph_sj)


def update_js_taxonomy(html_output, phylum_colors):
    selector_color = ''
    for phylum in phylum_colors:
        phylum_color = phylum_colors[phylum]
        selector_color += '''
        {
            selector: 'node[type="'''+phylum+'''"]',
            css: {
                'background-color': "'''+phylum_color+'''",
            }
        },
        '''

    js_folder = os.path.join(html_output, 'js')
    graph_js = os.path.join(js_folder, 'graph.js')
    new_graph_sj = ''
    with open(graph_js, 'r') as input_js:
        for line in input_js:
            if "data: { 'id'" in line:
                species_phylum_id = line.split("'id':")[1].split(',')[0].strip("'| ")[:4]
                line = line.replace(" } },", ", 'type': '"+species_phylum_id+"' } },")

            new_graph_sj += line
            if 'style: [' in line:
                new_graph_sj += selector_color

    with open(graph_js, 'w') as input_js:
        input_js.write(new_graph_sj)


def update_svg(svg_file, essentials, alternatives):
    new_svg = []
    line_before = ''
    with open(svg_file, 'r') as input_js:
        for line in input_js:
            if '<text' in line:
                species_id = line.split('>')[1].split('<')[0]
                if species_id in essentials:
                    line = line.replace('style="stroke:none;"', 'style="stroke:none;fill:green"')
                    line_before = line_before.replace('style="stroke:none;"', 'style="stroke:none;fill:green"')
                    new_svg[-1] = line_before
                if species_id in alternatives:
                    line = line.replace('style="stroke:none;"', 'style="stroke:none;fill:blue"')
                    line_before = line_before.replace('style="stroke:none;"', 'style="stroke:none;fill:blue"')
                    new_svg[-1] = line_before
            new_svg.append(line)
            line_before = line

    with open(svg_file, 'w') as input_js:
        input_js.write(''.join(new_svg))

def update_svg_taxonomy(svg_file, phylum_colors):
    new_svg = []
    line_before = ''
    with open(svg_file, 'r') as input_js:
        for line in input_js:
            if '<text' in line:
                species_phylum_id = line.split('>')[1].split('<')[0][:4]
                if species_phylum_id in phylum_colors:
                    phylum_color = phylum_colors[species_phylum_id]
                    line = line.replace('style="stroke:none;"', 'style="stroke:none;fill:{0};"'.format(phylum_color))
                    line_before = line_before.replace('style="stroke:none;"', 'style="stroke:none;fill:{0};"'.format(phylum_color))
                    new_svg[-1] = line_before
            new_svg.append(line)
            line_before = line

    with open(svg_file, 'w') as input_js:
        input_js.write(''.join(new_svg))