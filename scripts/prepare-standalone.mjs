import {cp,mkdir,access} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const app=path.join(root,'apps','web');
const standalone=path.join(app,'.next','standalone','apps','web');
await access(path.join(standalone,'server.js'));
for(const [source,destination] of [[path.join(app,'.next','static'),path.join(standalone,'.next','static')],[path.join(app,'public'),path.join(standalone,'public')]]){
  if(!path.resolve(destination).startsWith(path.join(app,'.next','standalone')+path.sep))throw new Error('Output must remain inside the standalone build');
  await mkdir(path.dirname(destination),{recursive:true});
  await cp(source,destination,{recursive:true,force:true});
}
console.log('Prepared standalone static assets and public artwork.');
