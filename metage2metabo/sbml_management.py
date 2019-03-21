from padmet_utils.scripts.connection.pgdb_to_padmet import from_pgdb_to_padmet
from padmet_utils.scripts.connection.sbmlGenerator import padmet_to_sbml
from padmet_utils.scripts.connection.sbml_to_sbml import from_sbml_to_sbml
from padmet_utils.scripts.connection.sbml_to_padmet import from_sbml_to_padmet
from multiprocessing import Pool
from metage2metabo import utils
import os


def run_pgdb_to_sbml(species_multiprocess_data):
    """Function used in multiprocess to turn PGDBs into SBML2.

    Args:
        species_multiprocess_data (list): pathname to species pgdb dir, pathname to species sbml file

    Returns:
        sbml_check (bool): Check if sbml file exists
    """
    species_pgdb_dir = species_multiprocess_data[0]
    species_sbml_file = species_multiprocess_data[1]
    padmet = from_pgdb_to_padmet(
        species_pgdb_dir,
        'metacyc',
        '22.5',
        arg_verbose=False,
        arg_with_genes=True,
        arg_source=None,
        enhanced_db=None,
        padmetRef_file=None)

    padmet_to_sbml(padmet, species_sbml_file, sbml_lvl=2, verbose=False)

    sbml_check = utils.is_valid_path(species_sbml_file)

    return sbml_check


def pgdb_to_sbml(pgdb_dir, output_dir, cpu):
    """Turn Pathway Tools PGDBs into SBML2 files using Padmet
    
    Args:
        pgdb_dir (str): PGDB directory

    Returns:
        sbml_dir (str): SBML directory
    """
    sbml_dir = output_dir + "/sbml"
    if not utils.is_valid_dir(sbml_dir):
        logger.critical("Impossible to access/create output directory")
        sys.exit(1)

    pgdb_to_sbml_pool = Pool(processes=cpu)

    multiprocess_data = []
    for species in os.listdir(pgdb_dir):
        multiprocess_data.append(
            [pgdb_dir + '/' + species, sbml_dir + '/' + species + '.sbml'])

    sbml_checks = pgdb_to_sbml_pool.map(run_pgdb_to_sbml, multiprocess_data)

    pgdb_to_sbml_pool.close()
    pgdb_to_sbml_pool.join()

    if all(sbml_checks):
        return sbml_dir

    else:
        logger.critical("Error during padmet/sbml creation.")
        sys.exit(1)


def sbml3_to_sbml2(sbml_file, sbml_output_file, cpu, version):
    """Turn sbml3 to sbml2.

    Args:
        sbml_file (string): pathname to species sbml file
        sbml_output_file (string): pathname to output sbml file
        db (string): name of the database ('metacyc')
        version (string): version of tthe database

    Returns:
        sbml_check (bool): Check if sbml file exists
    """
    from_sbml_to_sbml(sbml_file, sbml_output_file, version, cpu)

    sbml_check = utils.is_valid_path(sbml_output_file)

    return sbml_check


def sbml2_to_sbml3(sbml_file, sbml_output_file, db, version):
    """Turn sbml2 to sbml3.

    Args:
        sbml_file (string): pathname to species sbml file
        sbml_output_file (string): pathname to output sbml file
        db (string): name of the database ('metacyc')
        version (string): version of tthe database

    Returns:
        sbml_check (bool): Check if sbml file exists
    """
    padmet = from_sbml_to_padmet(
        sbml=sbml_file,
        db=db,
        version=version,
        padmetSpec_file=None,
        source_tool=None,
        source_category=None,
        source_id=None,
        padmetRef_file=None,
        mapping=None,
        verbose=None)
    padmet_to_sbml(padmet, sbml_output_file, sbml_lvl=3, verbose=False)

    sbml_check = utils.is_valid_path(sbml_output_file)

    return sbml_check