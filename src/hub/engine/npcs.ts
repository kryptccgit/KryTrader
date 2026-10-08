
export interface Topic {
  ask: string;
  say: string[];
  next?: Topic[];
}

export interface Persona {
  id: string;
  name: string;
  title: string;
  greet: string[];
  bye: string[];
  topics: Topic[];
  barks: string[];
}

export const PERSONAS: Persona[] = [
  {
    id: 'Ada',
    name: 'Ada Vantablack',
    title: 'Signal Whisperer · Research Lab',
    greet: [
      'Shh. Shh. The dish is listening. Speak in lowercase.',
      'Oh, a visitor. The scanners said someone would come. They also said "beans", so, mixed record.',
    ],
    bye: ['Go quietly. The noise floor has ears.', 'If you hear a hum on your way out, do not hum back.'],
    barks: [
      'I keep the noise in a jar. The jar is full.',
      'That blip was nothing. That blip was ALSO nothing. Suspicious.',
      'The dish turned left by itself again.',
    ],
    topics: [
      {
        ask: 'What do you actually do here?',
        say: [
          'The scanners pour every market on the exchange into this room. Thousands of them, all talking at once.',
          'I listen for the ones that whisper. Whales. Momentum. A trade that moves before it should.',
          'Most of it is noise. I keep the noise. Someone has to.',
        ],
        next: [
          {
            ask: 'You keep the noise?',
            say: [
              'In a jar. Under my desk. It is labelled NOISE.',
              'Sometimes at night it is louder. I have filed a ticket with Gus. He says turbines do the same thing.',
            ],
          },
        ],
      },
      {
        ask: 'Is the dish... alive?',
        say: [
          'Alive is a strong word. Opinionated, certainly.',
          'It points at the markets it likes. It refuses to point at weather markets. We do not discuss the weather markets.',
        ],
      },
      {
        ask: 'Why do you whisper?',
        say: ['Because a signal that hears you coming changes its mind.', 'Also I lost my voice yelling at a bond chart in a previous life.'],
      },
    ],
  },
  {
    id: 'Rui',
    name: 'Rui Tabsworth',
    title: 'Keeper of the Unread Tabs · Research Lab',
    greet: [
      'Ah! Hold on, let me just — no, that is the wrong tab. Hello.',
      'Welcome, welcome. Mind the citations, they are load-bearing.',
    ],
    bye: ['I will bookmark this conversation. I will never open it again.', 'Farewell. See footnote.'],
    barks: [
      'I have never closed a tab. I never will.',
      'Source? Source. Source of the source?',
      'Footnote: see footnote.',
    ],
    topics: [
      {
        ask: 'How many tabs do you have open?',
        say: [
          'Enough that the browser now has its own weather.',
          'Somewhere in there is an article I opened during my first week. I think about it the way sailors think about the sea.',
        ],
      },
      {
        ask: 'What do you research?',
        say: [
          'Whatever Ada flags. She hears it; I find out why it happened.',
          'Who settles a market. What the rules really say. Whether "by the end of the day" means the end of the day or the end of somebody\'s day.',
        ],
        next: [
          {
            ask: 'Does that matter much?',
            say: ['It is the only thing that matters. A market is a promise, and promises have fine print.', 'I read the fine print so the fine print does not read you.'],
          },
        ],
      },
      {
        ask: 'Why do you talk in footnotes?',
        say: ['I do not talk in footnotes.¹', '¹ I do.'],
      },
    ],
  },
  {
    id: 'Bo',
    name: 'Bo the Unquenched',
    title: 'Master Smith · Strategy Forge',
    greet: ['HAH! A NEW FACE! COME, STAND BY THE FIRE!', 'YOU. YES, YOU. DO YOU RESPECT HEAT?'],
    bye: ['GO, AND MAY YOUR EDGES STAY SHARP!', 'TELL THE OTHERS BO IS STILL BURNING!'],
    barks: ['IF IT IS NOT ON FIRE, IS IT EVEN A STRATEGY?', 'GERALD! STAY IN THE FURNACE!', 'MORE COAL!'],
    topics: [
      {
        ask: 'Why are you shouting?',
        say: ['THE FURNACE IS LOUD!', '...', 'It is not loud. I just like it.'],
      },
      {
        ask: 'What gets forged here?',
        say: [
          'STRATEGIES! Rules for when to buy and when to walk away.',
          'Raw ideas come in through that inbox. I heat them until the weak parts melt off. What survives goes to the Backtest Chamber to be tested against the past.',
          'Most of them do not survive. THAT IS THE POINT.',
        ],
      },
      {
        ask: 'Who is Gerald?',
        say: ['Gerald is an ember. Gerald has been burning since the ship was built.', 'Do not look directly at Gerald. He gets shy and goes out. We relight him every time. It is still Gerald.'],
        next: [
          {
            ask: 'Is it still Gerald, though?',
            say: ['...', 'GET OUT OF MY FORGE.'],
          },
        ],
      },
    ],
  },
  {
    id: 'Kit',
    name: 'Kit Anvilsong',
    title: 'Apprentice Smith (Self-Declared Poet) · Strategy Forge',
    greet: ['Oh! A listener! Would you like to hear my poem? It is about the anvil.', 'Hi! Bo says I am not allowed to recite near the coals anymore.'],
    bye: ['Wait, I have a closing couplet — oh, you are already leaving.', 'Bye! I will write you a verse. It will rhyme with anvil. Badly.'],
    barks: ['O anvil, my anvil, thou flat metal flannel...', 'Hit it harder, edge gets larger. That is how it works. Right? Right.', 'Nothing rhymes with anvil. I have checked.'],
    topics: [
      {
        ask: 'Let me hear the poem.',
        say: [
          'Ahem. "Upon the anvil, strong and flannel, / I struck a rule, it took the channel."',
          '"And though Bo said the rule was bad, / it was the finest rule I had."',
          'It is a work in progress. Like me. Like all of us.',
        ],
      },
      {
        ask: 'What does an apprentice do?',
        say: ['I hold things. I hand Bo things. I hit things when he is on lunch.', 'I believe that if you hit a strategy hard enough it gets more edge. Bo says that is not how anything works. I am collecting evidence.'],
      },
    ],
  },
  {
    id: 'Quinn',
    name: 'Quinn Hindsight',
    title: 'Historian of Prices · Backtest Chamber',
    greet: ['You are... from now? Fascinating. I rarely go there.', 'Ah, a visitor from the out-of-sample. Please wipe your feet.'],
    bye: ['Go safely into the future. Write down what happens. I will want to test it later.', 'Goodbye. I will remember this perfectly, which is the problem.'],
    barks: ['Everything worked in the past. That is what worries me.', 'Do not tell me what happens next. I want to be surprised. Statistically.', 'The past is the only market that never closes.'],
    topics: [
      {
        ask: 'What is the Backtest Chamber?',
        say: [
          'Every strategy Bo forges comes here. We run it against what the markets actually did, before it is allowed near anything real.',
          'If it only works on one lucky week, we find out here, where it is cheap to find out.',
        ],
        next: [
          {
            ask: 'And if it passes?',
            say: ['Then it has survived the past.', 'The future is ruder. But at least it is not naive.'],
          },
        ],
      },
      {
        ask: 'Why are you afraid of the present?',
        say: ['Because nobody has graded it yet.', 'In the past, every answer is in the back of the book. Out there, the book is still being written, and the author is very bad at foreshadowing.'],
      },
    ],
  },
  {
    id: 'Nova',
    name: 'Nova Overfit',
    title: 'Keeper of the Infinite Tape · Backtest Chamber',
    greet: ['Before you say anything: are you real, or are you a parameter?', 'Oh good, a variable. Stand still, I need to fit you.'],
    bye: ['Do not generalise from this conversation. It was a small sample.', 'Leaving already? Classic out-of-sample behaviour.'],
    barks: ['The tape goes on forever. I have checked twice.', 'I fit a curve to my lunch. It predicted dessert perfectly. Never again.', 'If a backtest is too good, it is lying. Mine is always too good.'],
    topics: [
      {
        ask: 'What is on the tape?',
        say: ['Every price, every tick, everything the markets did while you were asleep.', 'I feed it to the machine and the machine tells us whether a strategy would have made it. It is like a time machine that only goes backwards and only does maths.'],
      },
      {
        ask: 'Why do you think you are a simulation?',
        say: [
          'Everything here works a little too well. The coffee is always the right temperature.',
          'I think somebody is backtesting me. If I perform too well, they will throw me out for overfitting.',
          'So I have started making small, believable mistakes. Like this conversation.',
        ],
      },
    ],
  },
  {
    id: 'Tess',
    name: 'Tess Farewell',
    title: 'Order Clerk, Very Emotional · Trading Desk',
    greet: ['Hello! Sorry, I have been crying a little. I just sent one off.', 'Oh! Are you here to see the orders go? It is so beautiful. And sad.'],
    bye: ['Goodbye! I say goodbye to everything that leaves. Including you.', 'Go. Go! Before I get attached.'],
    barks: ['Goodbye, little order. Be brave. Fill well.', 'Every one of them comes back changed.', 'Into the tube you go. I believe in you.'],
    topics: [
      {
        ask: 'Where do the orders go?',
        say: [
          'Through that tube, out of the ship, to the exchange — that big glowing ring outside.',
          'Some fill. Some sit there waiting for a price that never comes. Some get cancelled and come home. I hug those.',
        ],
      },
      {
        ask: 'Why are you so sad about it?',
        say: [
          'They are so small when they leave. Just a ticker, a side, a price.',
          'And they are going out into a market full of whales.',
          'I write each one a note. The exchange does not read them. I know. I still write them.',
        ],
        next: [
          {
            ask: 'What do the notes say?',
            say: ['"Stay within your limit." "Do not chase." "Call if you get lonely."', 'Standard stuff.'],
          },
        ],
      },
    ],
  },
  {
    id: 'Max',
    name: 'Max Sizewell',
    title: 'Senior Conviction Officer · Trading Desk',
    greet: ['This. Is. The. One.', 'You look like someone who appreciates a FULL SEND.'],
    bye: ['Remember: fortune favours the bold, and Rex favours the paperwork.', 'Go big. Within the caps. Rex is watching.'],
    barks: ['This is the trade of a lifetime. Again.', 'Rex says no. Rex always says no.', 'Size? Yes.'],
    topics: [
      {
        ask: 'Is every trade the trade of a lifetime?',
        say: ['Every single one.', 'I have had many lifetimes.', 'Rex calls them "strike reports".'],
      },
      {
        ask: 'Why does Rex keep stopping you?',
        say: [
          'Because the ship has rails. Caps on every order, caps on the day, a stop if the day goes bad.',
          'I push. The rails push back. The rails always win.',
          'Honestly? Thank god for the rails.',
        ],
      },
      {
        ask: 'Have you ever been unsure about anything?',
        say: ['Once. It was a sandwich.', 'I bought the whole sandwich anyway.'],
      },
    ],
  },
  {
    id: 'Goldie',
    name: 'Goldie Coinbiter',
    title: 'Vault Warden · Win/Loss Vault',
    greet: ['Halt! Open your mouth. ...Fine, you are not a coin. Proceed.', 'Mm. You have the look of someone who has never bitten a coin. Tragic.'],
    bye: ['Go. And if anyone offers you a coin, bite it first.', 'Off you go. Do not touch the green one.'],
    barks: ['*crunch* Real.', '*crunch* Real. *crunch* ...also real.', 'Keep your hands where the coins can see them.'],
    topics: [
      {
        ask: 'Why do you bite the coins?',
        say: ['To see if they are real.', 'In this vault, only real wins get in. A win the exchange has not settled is not a win, it is a rumour. I do not bite rumours.'],
      },
      {
        ask: 'What is the green one?',
        say: [
          'Cursed.',
          'It showed up one night. Nobody put it there. It hums when the market moves.',
          'Penny wants to count it. I will not let her. Some coins should not be counted.',
        ],
        next: [
          {
            ask: 'Can I bite it?',
            say: ['Absolutely not.', '...', 'Maybe on your birthday.'],
          },
        ],
      },
    ],
  },
  {
    id: 'Penny',
    name: 'Penny Tallymark',
    title: 'Counter of Small Things · Win/Loss Vault',
    greet: ['Four hundred and — no. No! You made me lose count.', 'Hello. Please stand still. I am counting your shoelaces.'],
    bye: ['Goodbye. One goodbye. Counted.', 'Off you go. I am starting over. Again.'],
    barks: ['Seven hundred and... seven hundred and something.', 'I have counted the ceiling tiles. There is one extra.', 'Nobody move.'],
    topics: [
      {
        ask: 'What are you counting?',
        say: ['Everything. Coins. Rivets. The number of times Max says "the one".', 'The rivets are winning.'],
      },
      {
        ask: 'Do you ever finish?',
        say: [
          'Once. I finished counting everything in the vault.',
          'Then a new coin came in and I had to start again.',
          'That is the dream, you know. Having to start again because something good happened.',
        ],
      },
      {
        ask: 'What is the extra ceiling tile?',
        say: ['That is what I want to know.', 'Rex thinks it is a risk. Gus thinks it is a vent. Ada thinks it is listening. I think it is mocking me.'],
      },
    ],
  },
  {
    id: 'Rex',
    name: 'Rex Hedgeworth',
    title: 'Chief of Risk (Helmet Mandatory) · Win/Loss Vault',
    greet: ['Before we speak, please sign this waiver. Verbally. Say "I accept the risks of small talk."', 'Stop. Is that a loose shoelace? That is a trip hazard. Noted.'],
    bye: ['Walk, do not run. Running is how tails happen.', 'Leave by the marked exit. All other exits are theoretical.'],
    barks: ['That is a tail risk.', 'Everything is a tail risk if you look closely enough. I look very closely.', 'Helmets ON in the vault.'],
    topics: [
      {
        ask: 'Why the helmet?',
        say: ['Because nobody ever wore a helmet and regretted it.', 'Also something fell on Max once. It was his own expectations.'],
      },
      {
        ask: 'What does a risk officer do here?',
        say: [
          'I keep the rails on.',
          'Every order has a size limit. Every day has a spending limit. If the day goes badly, buying stops, and closing out never does.',
          'Nobody here, not even the AI agents, can turn those off. Including me. Especially me.',
        ],
        next: [
          {
            ask: 'Not even the AI agents?',
            say: ['Especially not the AI agents.', 'They can only narrow the rails, never widen them. I put that in their contract. I also put it in their soup.'],
          },
        ],
      },
      {
        ask: 'Is anything not a risk?',
        say: ['Sitting very still in a padded room.', 'And even then, the padding could be load-bearing.'],
      },
    ],
  },
  {
    id: 'Gus',
    name: 'Gus Spinwhistle',
    title: 'Turbine Psychologist · Optimizer',
    greet: ['Keep your voice down — the left turbine is in a mood.', 'Oh hey. The turbines like you. I can tell. They hummed a third higher.'],
    bye: ['Bye! Say goodbye to the turbines on your way out. They notice.', 'Mind the reactor, it is going through something.'],
    barks: ['There, there. Nobody is going to replace you.', 'The reactor and the left turbine are not speaking.', 'You hear that pitch? That is contentment.'],
    topics: [
      {
        ask: 'What is the Optimizer?',
        say: [
          'It is where we tune things. Try a setting, try another, keep what does better against the past.',
          'It only runs when someone asks it to. Nothing in here spins up on its own. Well. Except the turbines\' feelings.',
        ],
      },
      {
        ask: 'Turbines have moods?',
        say: [
          'Everything that spins has a mood.',
          'The left one is anxious. The right one is smug. The reactor is a teenager.',
          'My job is half engineering and half listening.',
        ],
        next: [
          {
            ask: 'What is the reactor upset about?',
            say: ['It wanted to be a furnace. Bo told it it did not have the heat for it.', 'We are working through it.'],
          },
        ],
      },
    ],
  },
  {
    id: 'Ivy',
    name: 'Ivy Overclock',
    title: 'Engineer, Has Not Slept · Optimizer',
    greet: ['hi hello yes i am awake. extremely awake.', 'Do you know what this dial does? Neither do I. Turning it anyway.'],
    bye: ['bye. if you see sleep, tell it i said no.', 'Off you go! I am going to turn this one to eleven.'],
    barks: ['Eleven. Every dial. Eleven.', 'Sleep is just downtime for people.', 'What if we tried... MORE?'],
    topics: [
      {
        ask: 'When did you last sleep?',
        say: ['Define "sleep".', 'Define "last".', 'I blinked slowly this morning. That counted.'],
      },
      {
        ask: 'What happens if you turn everything to eleven?',
        say: [
          'Gus says the turbines get stressed and the results look amazing for exactly one week of history.',
          'Nova calls it overfitting. I call it ambition.',
          'We are both right. She is more right.',
        ],
      },
    ],
  },
  {
    id: 'captain',
    name: 'Captain Mossy',
    title: 'Commander of the Krypt · Bridge',
    greet: ['Captain\'s log, supplemental: a visitor approaches the bridge. They look snack-adjacent.', 'At ease, crewmate. Unless you brought snacks. Then: attention.'],
    bye: ['Dismissed. Bring snacks next time. That is an order.', 'Captain\'s log: the visitor departs. I remain magnificent.'],
    barks: ['Captain\'s log: still magnificent.', 'Steady as she goes.', 'Who moved my chair? I am the only one who sits in it.'],
    topics: [
      {
        ask: 'What does the captain do?',
        say: [
          'I sit in the chair. I look at the stars. Occasionally I point.',
          'The crew does the work. The rails keep it safe. I keep morale high, mostly by being this handsome.',
        ],
      },
      {
        ask: 'What are you, exactly?',
        say: ['A captain.', 'Next question.'],
        next: [
          {
            ask: 'No, but like... species?',
            say: ['Captain.', 'It is a very exclusive species. You have to be born a captain. Or be very persistent.'],
          },
        ],
      },
      {
        ask: 'Where is the ship going?',
        say: [
          'Wherever the markets are.',
          'We do not move, technically. The markets come to us. It is very efficient. I came up with it. I did not come up with it.',
        ],
      },
    ],
  },
];

export const PERSONA_BY_ID = new Map(PERSONAS.map((p) => [p.id, p]));

export function agentPersona(label: string): Persona {
  return {
    id: `agent:${label}`,
    name: label,
    title: 'One of your AI agents',
    greet: ['...'],
    bye: ['...'],
    barks: [],
    topics: [
      {
        ask: 'Hello?',
        say: [
          `${label} doesn't chat. It's one of your AI agents: it talks through its tool calls, and every one of them shows up on this ship as it happens.`,
        ],
      },
    ],
  };
}
