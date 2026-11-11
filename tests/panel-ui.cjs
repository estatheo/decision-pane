// Exercise the actual inline UI script without launching or controlling a browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
class Element {
  constructor() { this.children = []; this.value = ''; }
  set id(value) { nodes.set(value, this); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener() {}
  setAttribute() {}
}
for (const id of ['refresh', 'connection', 'updated', 'city', 'error',
                  'decisions', 'decision-count', 'work', 'work-count']) {
  nodes.set(id, new Element());
}
const context = vm.createContext({
  document: {
    getElementById: id => nodes.get(id),
    createElement: () => new Element(),
    querySelector: () => ({content: 'test-token'}),
    addEventListener() {},
  },
  sessionStorage: {getItem: () => null},
  fetch: () => new Promise(() => {}),
  setInterval() {},
});
const html = fs.readFileSync(`${__dirname}/../gascity/lib/panel.html`, 'utf8');
vm.runInContext(html.match(/<script[^>]*>([\s\S]*?)<\/script>/)[1], context);
const decision = {id:'test-one',question:'Choose',options:[{label:'One'},{label:'Two'}],
                  pick:null,delivered:false,closed:false};
context.initialState = {decisions:[decision],work:[]};
vm.runInContext('state=initialState;render()', context);
const input = nodes.get('custom-answer');
input.value = 'An unfinished answer';
context.nextDecision = {...decision,id:'test-two'};
vm.runInContext('state.decisions.push(nextDecision);render()', context);
assert.equal(nodes.get('custom-answer'), input, 'a new queued decision must preserve the active input');
assert.equal(nodes.get('custom-answer').value, 'An unfinished answer');
assert.equal(nodes.get('decision-count').textContent, '· 2 waiting');
console.log('UI queue refresh preserves the active answer.');
