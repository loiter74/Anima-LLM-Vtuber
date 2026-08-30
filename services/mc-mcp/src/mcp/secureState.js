import { randomUUID } from 'node:crypto';
import { constants } from 'node:fs';
import {
  chmod,
  lstat,
  mkdir,
  open,
  rename,
  rm,
} from 'node:fs/promises';
import path from 'node:path';


const PRIVATE_DIRECTORY_MODE = 0o700;
const PRIVATE_FILE_MODE = 0o600;

const NO_FOLLOW = constants.O_NOFOLLOW ?? 0;
const EXCLUSIVE_WRITE_FLAGS = constants.O_WRONLY
  | constants.O_CREAT
  | constants.O_EXCL
  | NO_FOLLOW;


function privateStateError(code, target) {
  const error = new Error(`${code}:${target}`);
  error.code = code;
  return error;
}


function assertOwned(stats, target) {
  if (typeof process.getuid === 'function' && stats.uid !== process.getuid()) {
    throw privateStateError('PRIVATE_STATE_OWNER_MISMATCH', target);
  }
}


function assertDirectory(stats, target) {
  if (stats.isSymbolicLink()) throw privateStateError('PRIVATE_STATE_SYMLINK', target);
  if (!stats.isDirectory()) throw privateStateError('PRIVATE_STATE_NOT_DIRECTORY', target);
  assertOwned(stats, target);
}


function assertRegularFile(stats, target) {
  if (stats.isSymbolicLink()) throw privateStateError('PRIVATE_STATE_SYMLINK', target);
  if (!stats.isFile()) throw privateStateError('PRIVATE_STATE_NOT_FILE', target);
  assertOwned(stats, target);
}


async function inspectFile(file, allowMissing = false) {
  try {
    const stats = await lstat(file);
    assertRegularFile(stats, file);
    return stats;
  } catch (error) {
    if (allowMissing && error.code === 'ENOENT') return null;
    throw error;
  }
}


export async function ensurePrivateStateDirectory(directory) {
  await mkdir(directory, { recursive: true, mode: PRIVATE_DIRECTORY_MODE });
  const stats = await lstat(directory);
  assertDirectory(stats, directory);
  await chmod(directory, PRIVATE_DIRECTORY_MODE);
}


async function tightenExistingFile(file) {
  const stats = await inspectFile(file, true);
  if (stats) await chmod(file, PRIVATE_FILE_MODE);
}


export async function openPrivateStateFile(file) {
  await ensurePrivateStateDirectory(path.dirname(file));
  await tightenExistingFile(file);
  const handle = await open(file, EXCLUSIVE_WRITE_FLAGS, PRIVATE_FILE_MODE);
  try {
    const stats = await handle.stat();
    assertRegularFile(stats, file);
    await handle.chmod(PRIVATE_FILE_MODE);
    return handle;
  } catch (error) {
    await handle.close();
    throw error;
  }
}


export async function readPrivateStateFile(file, encoding = 'utf8') {
  await ensurePrivateStateDirectory(path.dirname(file));
  await tightenExistingFile(file);
  const handle = await open(file, constants.O_RDONLY | NO_FOLLOW);
  try {
    assertRegularFile(await handle.stat(), file);
    return await handle.readFile({ encoding });
  } finally {
    await handle.close();
  }
}


export async function writePrivateStateFile(file, contents) {
  const directory = path.dirname(file);
  await ensurePrivateStateDirectory(directory);
  await tightenExistingFile(file);
  const temporaryFile = path.join(
    directory,
    `.${path.basename(file)}.${process.pid}.${randomUUID()}.tmp`,
  );
  let handle = await openPrivateStateFile(temporaryFile);
  let renamed = false;
  try {
    await handle.writeFile(contents, { encoding: 'utf8' });
    await handle.sync();
    await handle.close();
    handle = null;
    await rename(temporaryFile, file);
    renamed = true;
    await chmod(file, PRIVATE_FILE_MODE);
  } finally {
    if (handle) await handle.close();
    if (!renamed) await rm(temporaryFile, { force: true, maxRetries: 5, retryDelay: 50 });
  }
}
