package android.view;

// XXX: not sure which sub-class to use
//public abstract class Window {
public class Window {
  public Window(Context context);

  public View findViewById(int id);
/*
  public abstract void setContentView(int layoutResID);
  public abstract void setContentView(View view);
  public abstract void setContentView(View view, ViewGroup.LayoutParams params);

  public abstract void addContentView(View view, ViewGroup.LayoutParams params);
*/

  public void setContentView(int layoutResID);
  public void setContentView(View view);
  public void setContentView(View view, ViewGroup.LayoutParams params);

  public void addContentView(View view, ViewGroup.LayoutParams params);

}
